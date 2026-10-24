import 'dart:io';
import 'api.dart';

/// Start the bundled Windows service only if no yf instance is already running.
/// User configuration and memory live outside the application installation.
Future<void> ensureBundledService(YfApi api) async {
  if (!Platform.isWindows ||
      !['127.0.0.1', 'localhost'].contains(api.base.host) ||
      api.base.port != 8765) {
    return;
  }
  try {
    await api.request('/api/status');
    return;
  } catch (_) {
    /* Try our bundled backend. */
  }
  final executable = File(
    '${File(Platform.resolvedExecutable).parent.path}/backend/yf-service.exe',
  );
  if (!await executable.exists()) return;
  final appData = Platform.environment['LOCALAPPDATA'];
  if (appData == null) return;
  final userRoot = Directory('$appData/your_friend');
  await userRoot.create(recursive: true);
  final config = File('${userRoot.path}/model.env');
  if (!await config.exists()) {
    await config.writeAsString(
      'YF_MODEL_BASE_URL=\nYF_MODEL_NAME=\nYF_MODEL_API_KEY=\nYF_MEMORY_MODEL=\n',
    );
  }
  await Process.start(
    executable.path,
    [],
    workingDirectory: userRoot.path,
    environment: {
      'YF_CONFIG_FILE': config.path,
      'YF_DATA_DIR': '${userRoot.path}/data',
    },
    mode: ProcessStartMode.detached,
  );
  for (int i = 0; i < 30; i++) {
    await Future<void>.delayed(const Duration(milliseconds: 250));
    try {
      await api.request('/api/status');
      return;
    } catch (_) {
      /* Wait for startup. */
    }
  }
}
