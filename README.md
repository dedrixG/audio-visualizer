# Audio Visualizer

Desktop visualizer for whatever the computer is playing. A phone on the same network can show the same view, including a black always-on layout for an OLED nightstand screen. The server listens on this computer only until you share it with `--bind 0.0.0.0`.

Styles: Bars, Mirror, Radial, Wave, Orbit, Gyro, Helix, Always-On.

Colors: Ion, Magma, Aurora, Mono, and Shuffle. Shuffle switches to a different set when the song changes. **Shuffle every** overrides that and fades through the four sets on a timer (15 seconds to 10 minutes). The timer is saved in that browser.

## Windows

Download **AudioVisualizer-windows.zip** from the [releases](https://github.com/dedrixG/audio-visualizer/releases). Unzip it. You get one folder.

1. Double-click `install.bat`.
2. It adds a Start Menu shortcut, a Desktop shortcut, and an entry under Settings, Apps. The firewall rule for port 8765 is added when Windows allows it.
3. Open **Audio Visualizer** from the shortcut, or double-click `start.bat`. It listens on this PC only. A phone needs `BIND=0.0.0.0` (see Phone).

Nothing is copied to Program Files. Python, the program, and the shortcuts' target all stay in that folder.

`uninstall.bat` in the same folder removes the shortcuts, the Settings entry, and the firewall rule. It then asks before deleting the folder.

System audio is the Windows "what you hear" loopback. Song changes follow the Windows media session (Spotify, a browser, and other players that publish one). The shuffle timer does not need that.

If you cloned the repo instead of downloading the zip, `install.bat` downloads a private Python 3.12 into `python\` inside the folder and installs the audio package there. You do not need a system-wide Python.

## Linux

Python 3 and `parec` (package `pulseaudio-utils` on Fedora) are required. Song shuffle also uses `python3-dbus`.

```bash
chmod +x start.sh
./start.sh
```

The script adds an application-menu entry and opens the visualizer. System audio is the default PipeWire or PulseAudio output monitor. The server listens on this computer only (`127.0.0.1`).

## Phone

True Samsung Always On Display cannot run a custom visualizer. This page is the workable version: a black OLED view that stays awake and can follow this computer's playback.

Share it on the network when a phone should open it:

```bash
BIND=0.0.0.0 ./start.sh
```

On Windows, set `BIND=0.0.0.0` in the command prompt before `start.bat`.

Anyone on the same network who opens that URL can hear what this computer is playing. Other websites cannot. The audio connection accepts only this server's own page: `http://127.0.0.1:<port>`, `http://localhost:<port>`, or the Wi-Fi / Tailscale address the phone opened.

Fedora's firewall may block the phone on Wi-Fi:

```bash
sudo firewall-cmd --add-port=8765/tcp
sudo firewall-cmd --add-port=8765/tcp --permanent
```

Tailscale addresses (`100.x`) usually work without that.

1. Leave the visualizer running on the computer.
2. On the phone, open the Wi-Fi or Tailscale URL printed in the window.
3. Chrome, Add to Home screen.
4. Set the app's battery use to Unrestricted.
5. Open it, tap Start, then Always-On.

## Keys

`F` fullscreen. `H` hides the controls. `Space` plays or pauses a loaded file.

## Sources

- **System** is the computer's playback.
- **Mic** is the browser microphone.
- **File** is a track you pick. Shuffle-by-song picks a new color for each file. The timer overrides that.
