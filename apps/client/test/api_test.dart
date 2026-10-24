import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:your_friend/api.dart';

void main() {
  test(
    'remote connections require HTTPS and never accept credentials in URLs',
    () {
      expect(() => YfApi('http://192.168.1.3:8765'), throwsFormatException);
      expect(
        () => YfApi('https://user:password@example.com'),
        throwsFormatException,
      );
      expect(
        () => YfApi('https://example.com/?token=secret'),
        throwsFormatException,
      );
      expect(YfApi.validateAddress('http://127.0.0.1:8765').host, '127.0.0.1');
    },
  );
  test(
    'stream preserves Chinese text split between network chunks and stops on completion',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final listener = server.listen((request) async {
        await utf8.decoder.bind(request).join();
        request.response.headers.contentType = ContentType(
          'text',
          'event-stream',
        );
        final bytes = utf8.encode(
          'event: delta\ndata: {"text":"你好，慢慢聊"}\n\nevent: done\ndata: {}\n\n',
        );
        for (final byte in bytes) {
          request.response.add([byte]);
          await request.response.flush();
        }
        await request.response.close();
      });
      final api = YfApi('http://127.0.0.1:${server.port}');
      try {
        final events = await api
            .chat('yf-companion', '你好', 'native-test-1')
            .toList();
        expect(events.first['text'], '你好，慢慢聊');
        expect(events.last['kind'], 'done');
      } finally {
        api.close();
        await listener.cancel();
        await server.close(force: true);
      }
    },
  );
  test('a disconnected stream is an error, not a completed answer', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final listener = server.listen((request) async {
      await utf8.decoder.bind(request).join();
      request.response.write('event: delta\ndata: {"text":"一部分"}\n\n');
      await request.response.close();
    });
    final api = YfApi('http://127.0.0.1:${server.port}');
    try {
      await expectLater(
        api.chat('yf-companion', '你好', 'native-test-2'),
        emitsInOrder([isA<Map<String, dynamic>>(), emitsError(isA<YfError>())]),
      );
    } finally {
      api.close();
      await listener.cancel();
      await server.close(force: true);
    }
  });
}
