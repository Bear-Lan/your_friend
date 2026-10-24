import 'dart:math' as math;
import 'package:flutter/material.dart';

enum Outfit { everyday, sailor, winter }

extension OutfitDetails on Outfit {
  String get label => ['日常针织', '海风学院', '冬日外套'][index];
  Color get color => [
    const Color(0xff81948a),
    const Color(0xff728aa1),
    const Color(0xffbb9f82),
  ][index];
}

/// Replaceable local illustration, with idle motion (not a 3D model).
class CompanionAvatar extends StatefulWidget {
  const CompanionAvatar({
    super.key,
    required this.outfit,
    required this.state,
    required this.paused,
  });
  final Outfit outfit;
  final String state;
  final bool paused;
  @override
  State<CompanionAvatar> createState() => _CompanionAvatarState();
}

class _CompanionAvatarState extends State<CompanionAvatar>
    with SingleTickerProviderStateMixin {
  late final animation = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 5),
  )..repeat();

  @override
  void dispose() {
    animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final active =
        !widget.paused &&
        !MediaQuery.disableAnimationsOf(context) &&
        TickerMode.valuesOf(context).enabled;
    if (active && !animation.isAnimating) animation.repeat();
    if (!active && animation.isAnimating) animation.stop();
    return Semantics(
      label: '二次元伙伴，${widget.outfit.label}',
      image: true,
      child: RepaintBoundary(
        child: AnimatedBuilder(
          animation: animation,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Image.asset(
              'assets/characters/${widget.outfit.name}.png',
              fit: BoxFit.contain,
              filterQuality: FilterQuality.medium,
            ),
          ),
          builder: (context, child) => Transform.translate(
            offset: Offset(
              0,
              active ? math.sin(animation.value * math.pi * 2) * 2 : 0,
            ),
            child: child,
          ),
        ),
      ),
    );
  }
}
