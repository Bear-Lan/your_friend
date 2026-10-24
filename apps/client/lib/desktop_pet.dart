import 'dart:io';
import 'package:flutter/services.dart';

/// Window operations are implemented by the Windows runner, without plugins.
class DesktopPet {
  static const channel = MethodChannel('app.yourfriend/desktop');
  static bool get supported => Platform.isWindows;

  static Future<void> call(String method, [Object? arguments]) async {
    await channel.invokeMethod<void>(method, arguments);
  }
}
