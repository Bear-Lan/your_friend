import 'dart:async';
import 'dart:convert';
import 'dart:io';

class YfApi {
  YfApi(String address) : base = validateAddress(address);
  final Uri base;
  final HttpClient _client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 10);
  HttpClient? _streamClient;

  static Uri validateAddress(String address) {
    final uri = Uri.parse(address.trim());
    final loopback = ['localhost', '127.0.0.1', '::1'].contains(uri.host);
    if ((!loopback && uri.scheme != 'https') ||
        !['http', 'https'].contains(uri.scheme) ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path != '' && uri.path != '/')) {
      throw const FormatException('请输入 yf 服务地址；远程连接需要 HTTPS。');
    }
    return uri;
  }

  Uri _uri(String path) => base.resolve(path);

  Future<dynamic> request(
    String path, {
    String method = 'GET',
    Object? body,
  }) async {
    final request = await _client.openUrl(method, _uri(path));
    request.headers.contentType = ContentType.json;
    if (body != null) request.write(jsonEncode(body));
    final response = await request.close().timeout(const Duration(seconds: 15));
    final text = await utf8.decoder
        .bind(response)
        .join()
        .timeout(const Duration(seconds: 15));
    final data = jsonDecode(text);
    if (response.statusCode >= 400) {
      throw YfError(
        data is Map && data['detail'] is String
            ? data['detail'] as String
            : '服务返回 ${response.statusCode}',
      );
    }
    return data;
  }

  Stream<Map<String, dynamic>> chat(
    String id,
    String content,
    String requestId,
  ) async* {
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 10);
    _streamClient = client;
    try {
      final request = await client.postUrl(_uri('/api/conversations/$id/chat'));
      request.headers.contentType = ContentType.json;
      request.write(jsonEncode({'content': content, 'request_id': requestId}));
      final response = await request.close().timeout(
        const Duration(seconds: 100),
      );
      if (response.statusCode >= 400) {
        final text = await utf8.decoder.bind(response).join();
        final data = jsonDecode(text);
        throw YfError(
          data is Map && data['detail'] is String
              ? data['detail'] as String
              : '服务返回 ${response.statusCode}',
        );
      }
      String kind = '';
      final lines = <String>[];
      bool ended = false;
      await for (final line
          in response
              .transform(utf8.decoder)
              .transform(const LineSplitter())
              .timeout(const Duration(seconds: 100))) {
        if (line.startsWith('event:')) kind = line.substring(6).trim();
        if (line.startsWith('data:')) lines.add(line.substring(5).trimLeft());
        if (line.isEmpty && lines.isNotEmpty) {
          final data = Map<String, dynamic>.from(
            jsonDecode(lines.join('\n')) as Map,
          );
          ended = ended || kind == 'done' || kind == 'error';
          yield {'kind': kind, ...data};
          kind = '';
          lines.clear();
        }
      }
      if (!ended) throw const YfError('连接中断，收到的回答已保留。');
    } finally {
      if (identical(_streamClient, client)) _streamClient = null;
      client.close(force: true);
    }
  }

  void stop() {
    _streamClient?.close(force: true);
    _streamClient = null;
  }

  void close() {
    stop();
    _client.close(force: true);
  }
}

class YfError implements Exception {
  const YfError(this.message);
  final String message;
  @override
  String toString() => message;
}
