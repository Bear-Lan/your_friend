import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Stores non-secret local UI preferences using each platform's app directory.
/// API keys remain on the yf service and are never written here.
class LocalPreferences {
  LocalPreferences._(this._values, this._file);
  final Map<String, dynamic> _values;
  final File? _file;
  Future<void> _pending = Future<void>.value();
  static Map<String, dynamic>? _mock;
  @visibleForTesting
  static void setMockInitialValues(Map<String, dynamic> values) {
    _mock = Map.of(values);
  }

  static Future<LocalPreferences> getInstance() async {
    if (_mock != null) return LocalPreferences._(_mock!, null);
    late String directory;
    if (Platform.isWindows) {
      final base = Platform.environment['LOCALAPPDATA'];
      if (base == null) {
        throw const FileSystemException('Local app directory is unavailable');
      }
      directory = '$base/your_friend';
    } else if (Platform.isAndroid) {
      directory =
          await const MethodChannel(
            'app.yourfriend/storage',
          ).invokeMethod<String>('appDirectory') ??
          (throw const FileSystemException(
            'Android app directory is unavailable',
          ));
    } else {
      throw UnsupportedError('This preview supports Windows and Android.');
    }
    final file = File('$directory/preferences.json');
    Map<String, dynamic> data = {};
    if (await file.exists()) {
      try {
        data = Map<String, dynamic>.from(
          jsonDecode(await file.readAsString()) as Map,
        );
      } on FormatException {
        /* Keep malformed preference file intact until next explicit save. */
      }
    }
    return LocalPreferences._(data, file);
  }

  String? getString(String key) =>
      _values[key] is String ? _values[key] as String : null;
  int? getInt(String key) => _values[key] is int ? _values[key] as int : null;
  Future<void> setString(String key, String value) => _save(key, value);
  Future<void> setInt(String key, int value) => _save(key, value);
  Future<void> _save(String key, Object value) {
    _values[key] = value;
    final snapshot = jsonEncode(_values);
    final file = _file;
    if (file == null) return Future<void>.value();
    final operation = _pending.catchError((Object _) {}).then((_) async {
      await file.parent.create(recursive: true);
      final temporary = File('${file.path}.tmp');
      await temporary.writeAsString(snapshot, flush: true);
      await temporary.rename(file.path);
    });
    _pending = operation;
    return operation;
  }
}
