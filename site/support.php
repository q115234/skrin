<?php
/**
 * «Скрин» — сообщения в поддержку (из программы и с сайта website18.ru/skrin/) → бот MAX, как ../send.php.
 * Токен бота — только в ../max-config.php (закрыт в .htaccess сайта).
 * Каждое сообщение сохраняется в ~/website18/skrin-support/ (вне public_html) вместе с журналом программы,
 * в MAX уходит короткая выжимка. Антиспам: ловушка-поле, проверка источника, не больше RATE_MAX за час с IP.
 */

header('Content-Type: application/json; charset=utf-8');

const STORE     = __DIR__ . '/../../skrin-support';
const RATE_MAX  = 5;
const RATE_SPAN = 3600;

function out(int $code, array $data): void {
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

function store_dir(): string {
    if (!is_dir(STORE)) {
        @mkdir(STORE, 0700, true);
    }
    return STORE;
}

function spam(string $reason, array $d): void {
    $f = store_dir() . '/spam.log';
    if (@filesize($f) > 1024 * 1024) {
        @rename($f, $f . '.old');
    }
    $row = ['time' => date('d.m.Y H:i:s'), 'reason' => $reason, 'ip' => $_SERVER['REMOTE_ADDR'] ?? '',
            'ua' => mb_substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 200),
            'contact' => mb_substr((string)($d['contact'] ?? ''), 0, 200),
            'message' => mb_substr((string)($d['message'] ?? ''), 0, 300)];
    @file_put_contents($f, json_encode($row, JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE) . "\n",
        FILE_APPEND | LOCK_EX);
    out(200, ['ok' => true]); // боту — «всё хорошо», чтобы не подбирал обход
}

function rate_limited(string $ip): bool {
    $fp = @fopen(store_dir() . '/rate.json', 'c+');
    if (!$fp) {
        return false;
    }
    flock($fp, LOCK_EX);
    $data = json_decode(stream_get_contents($fp) ?: '{}', true) ?: [];
    $now = time();
    foreach ($data as $k => $times) {
        $data[$k] = array_values(array_filter($times, fn($t) => $t > $now - RATE_SPAN));
        if (!$data[$k]) {
            unset($data[$k]);
        }
    }
    $limited = count($data[$ip] ?? []) >= RATE_MAX;
    if (!$limited) {
        $data[$ip][] = $now;
    }
    ftruncate($fp, 0);
    rewind($fp);
    fwrite($fp, json_encode($data));
    flock($fp, LOCK_UN);
    fclose($fp);
    return $limited;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    out(405, ['ok' => false, 'error' => 'method']);
}

$isJson = stripos($_SERVER['CONTENT_TYPE'] ?? '', 'application/json') !== false;
$d = $isJson ? (json_decode(file_get_contents('php://input'), true) ?: []) : $_POST;

if (!empty($d['website'])) {
    spam('заполнено скрытое поле', $d);
}

$source = ($d['source'] ?? '') === 'app' ? 'app' : 'site';
if ($source === 'app') {
    if (empty($_SERVER['HTTP_X_SKRIN_APP']) || strpos($_SERVER['HTTP_USER_AGENT'] ?? '', 'Skrin/') !== 0) {
        spam('не из программы', $d);
    }
} else {
    $origin = $_SERVER['HTTP_ORIGIN'] ?? ($_SERVER['HTTP_REFERER'] ?? '');
    $host = strtolower((string)parse_url($origin, PHP_URL_HOST));
    if ($host !== 'website18.ru' || strpos($_SERVER['HTTP_ACCEPT'] ?? '', 'application/json') === false) {
        spam('не через форму сайта', $d);
    }
}

$contact = trim((string)($d['contact'] ?? ''));
$message = trim((string)($d['message'] ?? ''));
$name    = trim((string)($d['name'] ?? ''));
if (mb_strlen($message) < 5 || mb_strlen($contact) < 3) {
    out(400, ['ok' => false, 'error' => 'missing fields']);
}
if (mb_strlen($message) > 3000 || mb_strlen($contact) > 200 || mb_strlen($name) > 100) {
    out(400, ['ok' => false, 'error' => 'too long']);
}
if (rate_limited($_SERVER['REMOTE_ADDR'] ?? '')) {
    spam('больше ' . RATE_MAX . ' сообщений за час с одного IP', $d);
}

$info = is_array($d['info'] ?? null) ? $d['info'] : [];
$log  = mb_substr((string)($d['log'] ?? ''), -60000);
$id   = date('Y-m-d_His') . '_' . bin2hex(random_bytes(3));
@file_put_contents(store_dir() . "/$id.json", json_encode([
    'id' => $id, 'time' => date('d.m.Y H:i:s'), 'source' => $source, 'ip' => $_SERVER['REMOTE_ADDR'] ?? '',
    'ua' => $_SERVER['HTTP_USER_AGENT'] ?? '', 'name' => $name, 'contact' => $contact, 'message' => $message,
    'info' => $info, 'log' => $log,
], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT | JSON_INVALID_UTF8_SUBSTITUTE), LOCK_EX);

$lines = ['🛟 Скрин — сообщение в поддержку ' . ($source === 'app' ? '(из программы)' : '(с сайта)'), ''];
if ($name !== '') {
    $lines[] = "👤 Имя: $name";
}
$lines[] = "📮 Контакт: $contact";
$lines[] = '💬 ' . $message;
$lines[] = '';
if ($info) {
    $parts = [];
    foreach (['version' => 'версия', 'windows' => 'Windows', 'screens' => 'экраны', 'scale' => 'масштаб',
              'encoder' => 'видео'] as $k => $t) {
        if (!empty($info[$k])) {
            $parts[] = "$t: " . mb_substr((string)$info[$k], 0, 80);
        }
    }
    $lines[] = '🖥 ' . implode(' · ', $parts);
}
if ($log !== '') {
    $lines[] = '📎 Журнал программы приложен (' . round(strlen($log) / 1024) . " КБ): skrin-support/$id.json";
}
$lines[] = '⏰ ' . date('d.m.Y H:i');

$config = @include __DIR__ . '/../max-config.php';
if (is_array($config) && !empty($config['token'])) {
    $to = !empty($config['chat_id']) ? 'chat_id=' . $config['chat_id'] : 'user_id=' . $config['user_id'];
    $ch = curl_init('https://platform-api2.max.ru/messages?' . $to);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => json_encode(['text' => mb_substr(implode("\n", $lines), 0, 3900)],
            JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE),
        CURLOPT_HTTPHEADER     => ['Authorization: ' . $config['token'], 'Content-Type: application/json'],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 10,
    ]);
    $res = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($res === false || $code !== 200) {
        @file_put_contents(store_dir() . '/max-fail.log', date('d.m.Y H:i:s') . " $id HTTP $code\n", FILE_APPEND);
    }
}

// сообщение сохранено в любом случае — человеку отвечаем «отправлено»
out(200, ['ok' => true]);
