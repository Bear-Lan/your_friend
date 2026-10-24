package app.yourfriend.your_friend

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "app.yourfriend/storage")
            .setMethodCallHandler { call, result ->
                if (call.method == "appDirectory") result.success(filesDir.absolutePath)
                else result.notImplemented()
            }
    }
}
