# ChatGPT Android Remote Relay
Railway WebSocket web console and Kotlin accessibility controller for the official ChatGPT Android application. The app does not patch ChatGPT or use an internal API.

## Security
Set distinct CONSOLE_TOKEN and DEVICE_TOKEN in Railway. Only one device connects at a time. Web UI accepts the console token; Android controller accepts WSS URL and device token. This is a testing prototype; do not send passwords or private personal data through diagnostic snapshots.

## Run
Railway service root directory: /chatgpt-android-relay/web
Web health: /health
WSS: /ws

Android: Install both the official ChatGPT app and the controller. Save WSS URL + device token in controller. Enable its AccessibilityService in Android settings, log into ChatGPT, keep screen unlocked. The controller attempts to click send and returns accessibility snapshots to the website. Response bubble parsing, Drive files and unattended execution are not yet implemented.
