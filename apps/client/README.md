# your friend 原生客户端

Flutter 3.47.8 / Dart 3.13.7。Windows 是小型桌宠，Android 是手机聊天页面，使用原生 Flutter 渲染。依赖只有 Flutter SDK，无 WebView、无 Windows Developer Mode 要求。

## 使用 Windows 便携版

运行 `.local/releases/windows/your_friend.exe`，移动应用时复制整个 `windows` 目录（包括 DLL、data 和 backend），不能只复制 exe。默认桌宠约 220 × 320，点击展开聊天，拖动移动。右键角色 / 托盘图标访问衣橱、设置、置顶开关和退出；聊天右上角关闭会收回桌宠。

优先复用已运行的本机 yf 服务。如果 8765 没有服务，客户端尝试启动同目录的 `backend/yf-service.exe`，数据放在 `%LOCALAPPDATA%/your_friend/data`，模型配置为 `%LOCALAPPDATA%/your_friend/model.env`。首次创建的配置是空模板，请填写后重启服务。旧仓库的 `.env` 和数据库不会自动迁移；开发机原服务运行时仍使用原数据。

界面偏好存于 `%LOCALAPPDATA%/your_friend/preferences.json`。API 密钥只在服务端配置，不放入客户端或 APK。退出客户端不会结束供其他客户端共用的服务；可单独结束 `yf-service.exe`。运行日志位于 `%LOCALAPPDATA%/your_friend/logs/service.log`。

## Android 开发预览

Android 第一阶段通过 USB 调试连接电脑：

```powershell
adb reverse tcp:8765 tcp:8765
adb install -r .local/releases/android/your-friend-preview.apk
```

客户端地址保留 `http://127.0.0.1:8765`。包名 `app.yourfriend.yf.preview`，采用开发签名，不是公开发布版本。服务当前仅允许 loopback，正式网络配对 / 身份校验尚未实现，不能仅更改为局域网 IP 使用。远程地址在客户端要求 HTTPS；本地明文例外仅允许 localhost / 127.0.0.1。手机偏好保存在应用私有目录。

## 构建与检查

需要 Flutter 3.47.8。Windows 需要带 C++ 桌面开发组件的 Visual Studio；Android 需要 JDK 17、Android SDK 36、NDK 28.2.13676358，以及 SDK 所需许可证。脚本可传入其他本地 SDK 路径：

```powershell
# 仓库根目录；后端打包还需要 uv
./tools/build-windows.ps1 -Flutter C:/sdk/flutter/bin/flutter.bat
./tools/build-android.ps1 -Flutter C:/sdk/flutter/bin/flutter.bat -AndroidSdk C:/sdk/android -Jdk C:/sdk/jdk17
# 客户端目录
flutter pub get
dart analyze
flutter test
```

输出为 `.local/releases/windows/` 和 `.local/releases/android/your-friend-preview.apk`。Android 公共发布需要单独配置正式签名，密钥文件不可提交。

角色素材位于 `assets/characters/`，目前为本地 SVG 渲染的二次元 2D 立绘与三套配色，可重画 / 替换 PNG 后构建。重新渲染：`uv run --with resvg-py python tools/make-character-assets.py`。尚未实现 Live2D / 3D、精细换装、语音和手机系统任务。
