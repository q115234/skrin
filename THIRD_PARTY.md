# Сторонние компоненты / Third-party components

Код «Скрина» распространяется по лицензии MIT (см. [LICENSE](LICENSE)). Установщик дополнительно содержит:
The Skrin source code is MIT-licensed (see [LICENSE](LICENSE)). The installer also bundles:

| Компонент / Component | Лицензия / License | Где взять исходники / Source |
|---|---|---|
| FFmpeg 8.1 (сборка BtbN, `bin/ffmpeg.exe`, запускается отдельным процессом / run as a separate process) | GPL v3 | https://ffmpeg.org/download.html · https://github.com/BtbN/FFmpeg-Builds |
| Qt 6 / PySide6 | LGPL v3 | https://code.qt.io · https://pypi.org/project/PySide6/ |
| PyAudioWPatch (PortAudio с поддержкой WASAPI loopback) | MIT | https://github.com/s0d3s/PyAudioWPatch |
| PortAudio | MIT | https://github.com/PortAudio/portaudio |
| Python 3 | PSF License | https://www.python.org |
| Inno Setup (сам установщик / the installer itself) | Inno Setup License | https://jrsoftware.org/isinfo.php |

FFmpeg не изменён и не встроен в код программы: «Скрин» вызывает `ffmpeg.exe` как отдельную программу.
FFmpeg is unmodified and not linked into Skrin: the app launches `ffmpeg.exe` as a separate program.
