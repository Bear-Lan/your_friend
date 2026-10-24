import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'preferences.dart';

import 'api.dart';
import 'avatar.dart';
import 'service_bootstrap.dart';
import 'desktop_pet.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const YourFriendApp());
}

class YourFriendApp extends StatelessWidget {
  const YourFriendApp({super.key, this.desktopPet});
  final bool? desktopPet;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'your friend',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      scaffoldBackgroundColor: const Color(0xfff6f5f0),
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xff697e73),
        surface: const Color(0xfffaf9f5),
      ),
      fontFamily: Platform.isWindows ? 'Microsoft YaHei' : null,
      textTheme: const TextTheme(
        bodyMedium: TextStyle(color: Color(0xff465149)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide.none,
        ),
      ),
    ),
    home: CompanionHome(desktopPet: desktopPet ?? DesktopPet.supported),
  );
}

class CompanionHome extends StatefulWidget {
  const CompanionHome({super.key, this.desktopPet = false});
  final bool desktopPet;
  @override
  State<CompanionHome> createState() => _CompanionHomeState();
}

class _CompanionHomeState extends State<CompanionHome> {
  final input = TextEditingController();
  final scroll = ScrollController();
  final inputFocus = FocusNode();
  YfApi api = YfApi('http://127.0.0.1:8765');
  LocalPreferences? preferences;
  String? conversationId;
  Map<String, dynamic>? status;
  List<Map<String, dynamic>> messages = [];
  Outfit outfit = Outfit.everyday;
  bool busy = false,
      loading = true,
      paused = false,
      stopped = false,
      moreHistory = false,
      paging = false;
  String avatarState = 'idle';
  String? error;
  int generation = 0;
  bool expanded = false;

  Future<void> expand(bool value) async {
    if (!widget.desktopPet) return;
    if (!value) Navigator.of(context).popUntil((route) => route.isFirst);
    setState(() => expanded = value);
    await DesktopPet.call('setExpanded', value);
    if (value) bottom();
  }

  Future<void> desktopCommand(MethodCall call) async {
    if (!mounted) return;
    if (call.method == 'collapse') {
      await expand(false);
      return;
    }
    await expand(true);
    if (!mounted) return;
    await WidgetsBinding.instance.endOfFrame;
    if (!mounted) return;
    if (call.method == 'wardrobe') await wardrobe();
    if (call.method == 'settings') await settings();
  }

  Widget pet() => Scaffold(
    backgroundColor: const Color(0xff010203),
    body: GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => expand(true),
      onPanStart: (_) => DesktopPet.call('beginDrag'),
      onSecondaryTapUp: (_) => DesktopPet.call('showMenu'),
      child: Stack(
        children: [
          Positioned.fill(
            top: 30,
            bottom: 4,
            child: CompanionAvatar(
              outfit: outfit,
              state: avatarState,
              paused: paused,
            ),
          ),
          Positioned(
            top: 4,
            left: 20,
            right: 20,
            child: Center(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: const Color(0xfff6f5f0),
                  borderRadius: BorderRadius.circular(18),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 5,
                  ),
                  child: Text(
                    busy ? '正在回应你…' : '我在，点我聊聊',
                    style: const TextStyle(
                      fontSize: 11,
                      color: Color(0xff596b60),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
  @override
  void initState() {
    super.initState();
    if (widget.desktopPet) {
      DesktopPet.channel.setMethodCallHandler(desktopCommand);
    }
    initialize();
  }

  Future<void> initialize() async {
    preferences = await LocalPreferences.getInstance();
    if (!mounted) return;
    final saved =
        preferences!.getString('service_address') ?? 'http://127.0.0.1:8765';
    try {
      final restored = YfApi(saved);
      api.close();
      api = restored;
    } catch (_) {
      /* Invalid old setting falls back to local service. */
    }
    final savedOutfit = preferences!.getInt('outfit') ?? 0;
    setState(() {
      outfit = Outfit.values[savedOutfit.clamp(0, Outfit.values.length - 1)];
    });
    await ensureBundledService(api);
    if (!mounted) return;
    await connect();
  }

  Future<void> connect() async {
    if (busy || paging) return;
    final ownGeneration = ++generation;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final newStatus = Map<String, dynamic>.from(
        await api.request('/api/status') as Map,
      );
      final companion =
          await api.request('/api/companion', method: 'POST') as Map;
      final rows =
          await api.request('/api/conversations/${companion['id']}/messages')
              as List;
      if (!mounted || generation != ownGeneration) return;
      setState(() {
        status = newStatus;
        conversationId = companion['id'] as String;
        messages = rows
            .map((row) => Map<String, dynamic>.from(row as Map))
            .toList();
        moreHistory = rows.length == 80;
      });
      bottom();
    } catch (_) {
      if (mounted && generation == ownGeneration) {
        setState(() {
          error = '暂时连不上 yf 服务。请确认电脑上的服务已启动，或在设置中检查连接地址。';
        });
      }
    } finally {
      if (mounted && generation == ownGeneration) {
        setState(() {
          loading = false;
        });
      }
    }
  }

  void bottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && scroll.hasClients) {
        scroll.jumpTo(scroll.position.maxScrollExtent);
      }
    });
  }

  Future<void> older() async {
    if (paging || busy || messages.isEmpty || conversationId == null) return;
    setState(() {
      paging = true;
    });
    try {
      final oldHeight = scroll.hasClients
          ? scroll.position.maxScrollExtent
          : 0.0;
      final oldOffset = scroll.hasClients ? scroll.offset : 0.0;
      final rows =
          await api.request(
                '/api/conversations/$conversationId/messages?before=${messages.first['seq']}',
              )
              as List;
      if (!mounted) return;
      setState(() {
        messages.insertAll(
          0,
          rows.map((r) => Map<String, dynamic>.from(r as Map)),
        );
        moreHistory = rows.length == 80;
      });
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && scroll.hasClients) {
          scroll.jumpTo(
            oldOffset + scroll.position.maxScrollExtent - oldHeight,
          );
        }
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          error = '更早的记录暂时没有加载成功。';
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          paging = false;
        });
      }
    }
  }

  Future<void> send() async {
    final text = input.text.trim();
    if (text.isEmpty || busy || loading || conversationId == null) return;
    if (status?['model_configured'] != true) {
      setState(() {
        error = '请先在电脑端配置聊天模型。';
      });
      return;
    }
    final answer = <String, dynamic>{
      'role': 'assistant',
      'content': '',
      'status': 'pending',
    };
    setState(() {
      busy = true;
      stopped = false;
      error = null;
      avatarState = 'thinking';
      messages.add({'role': 'user', 'content': text, 'status': 'completed'});
      messages.add(answer);
    });
    input.clear();
    bottom();
    final requestId =
        '${DateTime.now().microsecondsSinceEpoch}-${Random.secure().nextInt(1 << 32)}';
    try {
      await for (final event in api.chat(conversationId!, text, requestId)) {
        if (!mounted || stopped) break;
        setState(() {
          if (event['kind'] == 'delta') {
            answer['content'] = '${answer['content']}${event['text']}';
            avatarState = 'answering';
          }
          if (event['kind'] == 'done') answer['status'] = 'completed';
          if (event['kind'] == 'error') {
            error = event['message'] as String? ?? '回答未完成';
            answer['status'] = 'failed';
          }
        });
        bottom();
      }
    } catch (exception) {
      if (mounted && !stopped) {
        setState(() {
          error = exception is YfError ? exception.message : '连接中断，收到的内容会保留。';
          answer['status'] = 'failed';
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          if (stopped) answer['status'] = 'cancelled';
          busy = false;
          avatarState = 'idle';
        });
      }
    }
  }

  void stop() {
    stopped = true;
    api.stop();
  }

  @override
  void dispose() {
    if (widget.desktopPet) DesktopPet.channel.setMethodCallHandler(null);
    api.close();
    input.dispose();
    inputFocus.dispose();
    scroll.dispose();
    super.dispose();
  }

  Future<void> panel(String title, Widget child) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      constraints: const BoxConstraints(maxWidth: 760),
      builder: (context) => SizedBox(
        height: MediaQuery.sizeOf(context).height * .9,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 16, 12, 4),
              child: Row(
                children: [
                  Text(
                    title,
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const Spacer(),
                  IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
            Expanded(child: child),
          ],
        ),
      ),
    );
  }

  Future<void> wardrobe() async {
    await panel(
      '衣橱',
      StatefulBuilder(
        builder: (context, localSetState) => ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const Text(
              '换一身衣服，接着陪你。',
              style: TextStyle(color: Color(0xff879187)),
            ),
            const SizedBox(height: 24),
            for (final item in Outfit.values)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Card(
                  child: ListTile(
                    leading: CircleAvatar(
                      backgroundColor: item.color,
                      child: const Icon(Icons.checkroom, color: Colors.white),
                    ),
                    title: Text(item.label),
                    trailing: outfit == item
                        ? const Icon(Icons.check_circle)
                        : null,
                    onTap: () async {
                      setState(() => outfit = item);
                      localSetState(() {});
                      await preferences?.setInt('outfit', item.index);
                    },
                  ),
                ),
              ),
            const SizedBox(height: 20),
            const Text(
              '当前使用本地二次元立绘，支持三套配色。精细立绘、Live2D 和模型导入后续接入；换装不会改变记忆和性格。',
              style: TextStyle(fontSize: 12, color: Color(0xff879187)),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> settings() async {
    final address = TextEditingController(text: api.base.toString());
    String? settingsError;
    bool saving = false;
    await panel(
      '设置',
      StatefulBuilder(
        builder: (context, localSetState) => ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const Text(
              'yf 服务连接',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: address,
              enabled: !busy && !saving,
              decoration: const InputDecoration(
                labelText: '服务地址',
                hintText: 'http://127.0.0.1:8765',
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              '这里连接的是你的 yf 服务。模型 API 密钥只保存在服务端。Android 当前通过 USB 调试转发连接电脑；正式设备配对仍待实现。',
              style: TextStyle(fontSize: 12, color: Color(0xff879187)),
            ),
            if (settingsError != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  settingsError!,
                  style: const TextStyle(color: Colors.red),
                ),
              ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: busy || saving
                  ? null
                  : () async {
                      YfApi? candidate;
                      localSetState(() => saving = true);
                      try {
                        candidate = YfApi(address.text);
                        await candidate.request('/api/status');
                        if (!mounted || !context.mounted) {
                          candidate.close();
                          return;
                        }
                        api.close();
                        api = candidate;
                        candidate = null;
                        await preferences?.setString(
                          'service_address',
                          api.base.toString(),
                        );
                        if (context.mounted) Navigator.pop(context);
                        await connect();
                      } catch (_) {
                        candidate?.close();
                        if (context.mounted) {
                          localSetState(
                            () =>
                                settingsError = '连接失败。检查地址和服务状态；远程地址需要 HTTPS。',
                          );
                        }
                      } finally {
                        if (context.mounted) {
                          localSetState(() => saving = false);
                        }
                      }
                    },
              child: Text(saving ? '连接中……' : '保存并连接'),
            ),
            const SizedBox(height: 28),
            const Divider(),
            const SizedBox(height: 16),
            Text('模型：${status?['model_name'] ?? '未连接'}'),
            const SizedBox(height: 8),
            const Text(
              'Windows / Android 原生客户端 · 0.2.0',
              style: TextStyle(fontSize: 12, color: Color(0xff879187)),
            ),
            const SizedBox(height: 24),
            OutlinedButton.icon(
              onPressed: () => personality(),
              icon: const Icon(Icons.tune),
              label: const Text('交流倾向与记忆设置'),
            ),
          ],
        ),
      ),
    );
    // Disposal after route exit avoids listeners using a disposed controller during the closing animation.
    Future<void>.delayed(const Duration(milliseconds: 400), address.dispose);
  }

  Future<void> personality() async {
    if (status == null) return;
    final document = Map<String, dynamic>.from(
      status!['feature_profile']['document'] as Map,
    );
    final weights = Map<String, dynamic>.from(document['expression'] as Map);
    final version = status!['feature_profile']['version'];
    final labels = {
      'warmth': '温暖程度',
      'humor': '幽默倾向',
      'curiosity': '好奇倾向',
      'directness': '直接程度',
      'detail': '展开程度',
      'initiative': '话题主动程度',
    };
    bool memory = status!['settings']['memory_enabled'] as bool,
        auto = status!['settings']['auto_memory'] as bool,
        saving = false;
    String? failure;
    await panel(
      '交流倾向与记忆',
      StatefulBuilder(
        builder: (context, localSetState) => ListView(
          padding: const EdgeInsets.all(24),
          children: [
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('保存和使用长期记忆'),
              value: memory,
              onChanged: saving ? null : (v) => localSetState(() => memory = v),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('后台整理记忆'),
              subtitle: const Text('可能产生模型 API 用量'),
              value: auto,
              onChanged: saving ? null : (v) => localSetState(() => auto = v),
            ),
            const SizedBox(height: 20),
            for (final entry in labels.entries)
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(entry.value),
                      const Spacer(),
                      Text('${((weights[entry.key] as num) * 100).round()}'),
                    ],
                  ),
                  Slider(
                    value: (weights[entry.key] as num).toDouble(),
                    divisions: 20,
                    onChanged: saving
                        ? null
                        : (v) => localSetState(() => weights[entry.key] = v),
                  ),
                ],
              ),
            if (failure != null)
              Text(failure!, style: const TextStyle(color: Colors.red)),
            FilledButton(
              onPressed: saving
                  ? null
                  : () async {
                      localSetState(() => saving = true);
                      try {
                        document['expression'] = weights;
                        await api.request(
                          '/api/profile',
                          method: 'PUT',
                          body: {
                            'expected_version': version,
                            'document': document,
                          },
                        );
                        await api.request(
                          '/api/settings',
                          method: 'PATCH',
                          body: {'memory_enabled': memory, 'auto_memory': auto},
                        );
                        final refreshed = Map<String, dynamic>.from(
                          await api.request('/api/status') as Map,
                        );
                        if (mounted) setState(() => status = refreshed);
                        if (context.mounted) Navigator.pop(context);
                      } catch (exception) {
                        if (context.mounted) {
                          localSetState(
                            () => failure = exception is YfError
                                ? exception.message
                                : '保存失败，请关闭面板重试。',
                          );
                        }
                      } finally {
                        if (context.mounted) {
                          localSetState(() => saving = false);
                        }
                      }
                    },
              child: Text(saving ? '保存中……' : '保存'),
            ),
            const SizedBox(height: 12),
            const Text(
              '自动性格养成和模型微调尚未实现。',
              style: TextStyle(fontSize: 12, color: Color(0xff879187)),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> memories() async {
    final query = TextEditingController();
    List<dynamic>? rows;
    String? failure;
    bool searching = false;
    await panel(
      '我们的回忆',
      StatefulBuilder(
        builder: (context, localSetState) {
          Future<void> search() async {
            if (searching) return;
            localSetState(() => searching = true);
            try {
              final result =
                  await api.request(
                        '/api/memories?archive=true&q=${Uri.encodeQueryComponent(query.text.trim())}',
                      )
                      as List;
              if (context.mounted) {
                localSetState(() {
                  rows = result;
                  failure = null;
                });
              }
            } catch (_) {
              if (context.mounted) localSetState(() => failure = '回忆暂时没有加载成功。');
            } finally {
              if (context.mounted) localSetState(() => searching = false);
            }
          }

          return ListView(
            padding: const EdgeInsets.all(24),
            children: [
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: query,
                      onSubmitted: (_) => search(),
                      decoration: const InputDecoration(
                        hintText: '搜索事件、人物或关键词',
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    onPressed: searching ? null : search,
                    icon: const Icon(Icons.search),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              if (searching) const LinearProgressIndicator(),
              if (failure != null) Text(failure!),
              if (rows == null && !searching)
                TextButton(onPressed: search, child: const Text('看看已有回忆')),
              if (rows != null && rows!.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('这里还没有相关回忆。慢慢聊，我们会逐渐积累。'),
                ),
              for (final row in rows ?? [])
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(18),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          row['outline'] as String,
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                        if ((row['detail'] as String? ?? '').isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 10),
                            child: SelectableText(row['detail'] as String),
                          ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            Icon(
                              row['pinned'] == true
                                  ? Icons.bookmark
                                  : Icons.history,
                              size: 15,
                            ),
                            const SizedBox(width: 6),
                            Text(
                              '重要性 ${((row['importance'] as num) * 100).round()}',
                              style: const TextStyle(
                                fontSize: 11,
                                color: Color(0xff879187),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
    Future<void>.delayed(const Duration(milliseconds: 400), query.dispose);
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    if (widget.desktopPet &&
        (!expanded || size.width < 300 || size.height < 420)) {
      return pet();
    }
    final small = size.width < 720;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            if (widget.desktopPet)
              GestureDetector(
                behavior: HitTestBehavior.opaque,
                onPanStart: (_) => DesktopPet.call('beginDrag'),
                child: Row(
                  children: [
                    const SizedBox(width: 18),
                    const Expanded(
                      child: Text(
                        'your friend',
                        style: TextStyle(fontSize: 11),
                      ),
                    ),
                    IconButton(
                      tooltip: '收回桌宠',
                      onPressed: () => expand(false),
                      icon: const Icon(Icons.close, size: 18),
                    ),
                  ],
                ),
              ),
            Padding(
              padding: EdgeInsets.symmetric(
                horizontal: small ? 20 : 42,
                vertical: widget.desktopPet ? 4 : 18,
              ),
              child: Row(
                children: [
                  const Text(
                    'yf',
                    style: TextStyle(
                      fontSize: 34,
                      fontFamily: 'Georgia',
                      fontStyle: FontStyle.italic,
                      color: Color(0xff697e73),
                    ),
                  ),
                  const SizedBox(width: 14),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'your friend',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        Text(
                          '你的日常，有我在场。',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 10,
                            color: Color(0xff939b91),
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: '衣橱',
                    onPressed: wardrobe,
                    icon: const Icon(Icons.checkroom_outlined),
                  ),
                  IconButton(
                    tooltip: '回忆',
                    onPressed: memories,
                    icon: const Icon(Icons.auto_awesome_outlined),
                  ),
                  IconButton(
                    tooltip: '设置',
                    onPressed: settings,
                    icon: const Icon(Icons.tune),
                  ),
                ],
              ),
            ),
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final stage = Stack(
                    children: [
                      Positioned.fill(
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            gradient: RadialGradient(
                              colors: [
                                outfit.color.withValues(alpha: .13),
                                const Color(0x00f6f5f0),
                              ],
                              radius: .8,
                            ),
                          ),
                        ),
                      ),
                      Positioned.fill(
                        child: CompanionAvatar(
                          outfit: outfit,
                          state: avatarState,
                          paused: paused,
                        ),
                      ),
                      Positioned(
                        left: small ? 18 : 44,
                        top: 10,
                        child: const Text(
                          'OUR LITTLE SPACE',
                          style: TextStyle(
                            fontSize: 9,
                            letterSpacing: 2,
                            color: Color(0xff9aa18f),
                          ),
                        ),
                      ),
                      Positioned(
                        bottom: 12,
                        left: 0,
                        right: 0,
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            DecoratedBox(
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: .8),
                                borderRadius: BorderRadius.circular(24),
                              ),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 20,
                                  vertical: 10,
                                ),
                                child: Text(
                                  avatarState == 'thinking'
                                      ? '让我想一想……'
                                      : avatarState == 'answering'
                                      ? '正在回应你……'
                                      : '我在，慢慢说。',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: Color(0xff7a8779),
                                  ),
                                ),
                              ),
                            ),
                            IconButton(
                              tooltip: paused ? '播放动作' : '暂停动作',
                              onPressed: () => setState(() => paused = !paused),
                              icon: Icon(
                                paused
                                    ? Icons.play_arrow_rounded
                                    : Icons.pause_rounded,
                                size: 17,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  );
                  final conversation = Padding(
                    padding: EdgeInsets.fromLTRB(
                      small ? 22 : 26,
                      small ? 8 : 26,
                      small ? 22 : 50,
                      12,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (!small)
                          const Padding(
                            padding: EdgeInsets.only(bottom: 18),
                            child: Text(
                              'JUST YOU & ME',
                              style: TextStyle(
                                letterSpacing: 2,
                                fontSize: 9,
                                color: Color(0xff9aa18f),
                              ),
                            ),
                          ),
                        if (error != null)
                          Container(
                            margin: const EdgeInsets.only(bottom: 12),
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: const Color(0xfff0e7dc),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    error!,
                                    style: const TextStyle(
                                      fontSize: 11,
                                      color: Color(0xff997456),
                                    ),
                                  ),
                                ),
                                IconButton(
                                  tooltip: '重新连接',
                                  onPressed: busy ? null : connect,
                                  icon: const Icon(Icons.refresh, size: 16),
                                ),
                              ],
                            ),
                          ),
                        Expanded(
                          child: loading
                              ? const Center(child: CircularProgressIndicator())
                              : messages.isEmpty
                              ? Center(
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        '今天，也陪着你。',
                                        style: TextStyle(
                                          fontSize: small ? 26 : 34,
                                          fontWeight: FontWeight.w500,
                                          color: const Color(0xff39483e),
                                        ),
                                      ),
                                      const SizedBox(height: 16),
                                      const Text(
                                        '不用想好开场白。\n开心的、琐碎的，都可以慢慢说给我听。',
                                        style: TextStyle(
                                          fontSize: 12,
                                          height: 2,
                                          color: Color(0xff929b90),
                                        ),
                                      ),
                                    ],
                                  ),
                                )
                              : ListView.builder(
                                  controller: scroll,
                                  itemCount:
                                      messages.length + (moreHistory ? 1 : 0),
                                  itemBuilder: (context, index) {
                                    if (moreHistory && index == 0) {
                                      return TextButton(
                                        onPressed: paging ? null : older,
                                        child: Text(
                                          paging ? '正在加载……' : '查看更早的记录',
                                        ),
                                      );
                                    }
                                    final message =
                                            messages[index -
                                                (moreHistory ? 1 : 0)],
                                        user = message['role'] == 'user';
                                    final failed = [
                                      'failed',
                                      'cancelled',
                                      'interrupted',
                                    ].contains(message['status']);
                                    return Align(
                                      alignment: user
                                          ? Alignment.centerRight
                                          : Alignment.centerLeft,
                                      child: Container(
                                        constraints: const BoxConstraints(
                                          maxWidth: 540,
                                        ),
                                        margin: const EdgeInsets.only(
                                          bottom: 16,
                                        ),
                                        padding: const EdgeInsets.all(15),
                                        decoration: BoxDecoration(
                                          color: user
                                              ? const Color(0xffe4eae1)
                                              : Colors.white.withValues(
                                                  alpha: .7,
                                                ),
                                          borderRadius: BorderRadius.circular(
                                            16,
                                          ),
                                        ),
                                        child: Column(
                                          crossAxisAlignment:
                                              CrossAxisAlignment.start,
                                          children: [
                                            Text(
                                              user ? '你' : 'yf',
                                              style: const TextStyle(
                                                fontSize: 10,
                                                color: Color(0xff96a08e),
                                              ),
                                            ),
                                            const SizedBox(height: 6),
                                            SelectableText(
                                              (message['content'] as String)
                                                      .isEmpty
                                                  ? (failed ? '暂时没有收到回答。' : '…')
                                                  : message['content']
                                                        as String,
                                              style: const TextStyle(
                                                fontSize: 13,
                                                height: 1.8,
                                              ),
                                            ),
                                            if (failed)
                                              const Text(
                                                '回答未完成',
                                                style: TextStyle(
                                                  fontSize: 10,
                                                  color: Color(0xffaa7b69),
                                                ),
                                              ),
                                          ],
                                        ),
                                      ),
                                    );
                                  },
                                ),
                        ),
                        const SizedBox(height: 12),
                        Container(
                          padding: const EdgeInsets.fromLTRB(16, 10, 10, 8),
                          decoration: BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.circular(20),
                            boxShadow: const [
                              BoxShadow(
                                color: Color(0x066e7e69),
                                blurRadius: 30,
                                offset: Offset(0, 6),
                              ),
                            ],
                          ),
                          child: Column(
                            children: [
                              CallbackShortcuts(
                                bindings: {
                                  const SingleActivator(
                                    LogicalKeyboardKey.enter,
                                  ): () {
                                    if (!HardwareKeyboard
                                        .instance
                                        .isShiftPressed) {
                                      send();
                                    }
                                  },
                                },
                                child: TextField(
                                  controller: input,
                                  focusNode: inputFocus,
                                  enabled: !busy,
                                  maxLength: 5000,
                                  minLines: 1,
                                  maxLines: 4,
                                  decoration: const InputDecoration(
                                    hintText: '说给我听吧……',
                                    counterText: '',
                                    filled: false,
                                    border: InputBorder.none,
                                    enabledBorder: InputBorder.none,
                                    focusedBorder: InputBorder.none,
                                  ),
                                  style: const TextStyle(fontSize: 13),
                                ),
                              ),
                              Row(
                                children: [
                                  Text(
                                    small
                                        ? '一直是我们，接着慢慢聊。'
                                        : 'Enter 发送 · Shift + Enter 换行',
                                    style: const TextStyle(
                                      fontSize: 9,
                                      color: Color(0xffa3aa9d),
                                    ),
                                  ),
                                  const Spacer(),
                                  IconButton.filled(
                                    onPressed: busy
                                        ? stop
                                        : loading || conversationId == null
                                        ? null
                                        : send,
                                    tooltip: busy ? '停止回答' : '发送',
                                    icon: Icon(
                                      busy
                                          ? Icons.stop_rounded
                                          : Icons.arrow_upward_rounded,
                                      size: 20,
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  );
                  if (small) {
                    return Column(
                      children: [
                        if (!widget.desktopPet)
                          SizedBox(
                            height: min(constraints.maxHeight * .38, 290),
                            child: stage,
                          ),
                        Expanded(child: conversation),
                      ],
                    );
                  }
                  return Row(
                    children: [
                      Expanded(child: stage),
                      Expanded(child: conversation),
                    ],
                  );
                },
              ),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(
                small ? 22 : 44,
                6,
                small ? 22 : 44,
                14,
              ),
              child: Row(
                children: [
                  const Text(
                    '一点一滴，慢慢相伴。',
                    style: TextStyle(fontSize: 9, color: Color(0xffa3aa9d)),
                  ),
                  const Spacer(),
                  Text(
                    loading
                        ? '连接中'
                        : status == null
                        ? '服务未连接'
                        : status!['model_configured'] == true
                        ? '${status!['model_name']} · 已配置'
                        : '模型未配置',
                    style: const TextStyle(
                      fontSize: 9,
                      color: Color(0xffa3aa9d),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
