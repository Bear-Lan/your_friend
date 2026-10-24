import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:your_friend/desktop_pet.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:your_friend/preferences.dart';
import 'package:your_friend/main.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  // These tests use a loopback server; bypass Flutter's canned HTTP 400 client.
  HttpOverrides.global = null;
  testWidgets('desktop pet expands and collapses without recreating the chat', (
    tester,
  ) async {
    final operations = <MethodCall>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      DesktopPet.channel,
      (call) async {
        operations.add(call);
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        DesktopPet.channel,
        null,
      ),
    );
    late HttpServer server;
    int companionRequests = 0;
    await tester.runAsync(() async {
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        request.response.headers.contentType = ContentType.json;
        if (request.uri.path == '/api/companion') companionRequests++;
        request.response.write(
          jsonEncode(
            request.uri.path == '/api/status'
                ? {'model_name': 'test', 'model_configured': false}
                : request.uri.path == '/api/companion'
                ? {'id': 'yf-companion'}
                : [
                    {
                      'role': 'assistant',
                      'content': '我们之前聊过的事情',
                      'status': 'completed',
                      'seq': 1,
                    },
                  ],
          ),
        );
        await request.response.close();
      });
    });
    LocalPreferences.setMockInitialValues({
      'service_address': 'http://127.0.0.1:${server.port}',
    });
    tester.view.physicalSize = const Size(220, 320);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.runAsync(() async {
      await tester.pumpWidget(const YourFriendApp(desktopPet: true));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await tester.pump();
    expect(find.text('我在，点我聊聊'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    await tester.tap(find.text('我在，点我聊聊'));
    await tester.pump();
    tester.view.physicalSize = const Size(420, 640);
    await tester.pump();
    expect(find.text('我们之前聊过的事情'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
    await tester.enterText(find.byType(TextField), '还没发出去的话');
    await tester.tap(find.byTooltip('收回桌宠'));
    await tester.pump();
    tester.view.physicalSize = const Size(220, 320);
    await tester.pump();
    await tester.tap(find.text('我在，点我聊聊'));
    await tester.pump();
    tester.view.physicalSize = const Size(420, 640);
    await tester.pump();
    expect(find.text('还没发出去的话'), findsOneWidget);
    expect(companionRequests, 1);
    expect(
      operations
          .where((call) => call.method == 'setExpanded')
          .map((call) => call.arguments),
      [true, false, true],
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.runAsync(() => server.close(force: true));
  });
  for (final size in [const Size(1200, 800), const Size(390, 844)]) {
    testWidgets('native companion layout and outfit restoration at $size', (
      tester,
    ) async {
      // Use a local HTTP server through runAsync because widget tests otherwise
      // intentionally block real IO and would only exercise an error screen.
      late HttpServer server;
      await tester.runAsync(() async {
        server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
        server.listen((request) async {
          final path = request.uri.path;
          request.response.headers.contentType = ContentType.json;
          request.response.write(
            jsonEncode(
              path == '/api/status'
                  ? {'model_name': 'test', 'model_configured': false}
                  : path == '/api/companion'
                  ? {'id': 'yf-companion'}
                  : [],
            ),
          );
          await request.response.close();
        });
      });
      LocalPreferences.setMockInitialValues({
        'service_address': 'http://127.0.0.1:${server.port}',
        'outfit': 1,
      });
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.runAsync(() async {
        await tester.pumpWidget(const YourFriendApp(desktopPet: false));
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump(const Duration(milliseconds: 30));
      expect(find.text('your friend'), findsOneWidget);
      expect(find.text('今天，也陪着你。'), findsOneWidget);
      expect(find.byTooltip('衣橱'), findsOneWidget);
      expect(find.textContaining('新建对话'), findsNothing);
      await tester.tap(find.byTooltip('衣橱'));
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      expect(find.text('海风学院'), findsOneWidget);
      await tester.tap(find.text('冬日外套'));
      await tester.pump();
      expect((await LocalPreferences.getInstance()).getInt('outfit'), 2);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.runAsync(() async {
        await server.close(force: true);
      });
    });
  }
}
