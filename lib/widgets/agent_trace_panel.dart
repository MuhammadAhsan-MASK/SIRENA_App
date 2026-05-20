import 'package:flutter/material.dart';
import 'dart:async';
import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:ciro/theme/app_theme.dart';
import 'package:ciro/services/data_service.dart';
import 'package:ciro/models/models.dart';

class ThoughtEntry {
  final DateTime timestamp;
  final String agentName;
  final String message;
  final ThoughtType type;

  ThoughtEntry({
    required this.timestamp,
    required this.agentName,
    required this.message,
    this.type = ThoughtType.info,
  });
}

enum ThoughtType { info, warning, success, critical }

class AgentTracePanel extends StatefulWidget {
  final String scenario;
  final String? sessionId;
  const AgentTracePanel({super.key, required this.scenario, this.sessionId});

  @override
  State<AgentTracePanel> createState() => _AgentTracePanelState();
}

class _AgentTracePanelState extends State<AgentTracePanel> {
  final List<ThoughtEntry> _entries = [];
  final ScrollController _scrollController = ScrollController();
  Timer? _timer;
  int _currentIndex = 0;
  StreamSubscription? _sseSubscription;

  @override
  void initState() {
    super.initState();
    _startDisplay();
  }

  @override
  void didUpdateWidget(AgentTracePanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.sessionId != widget.sessionId || oldWidget.scenario != widget.scenario) {
      _resetDisplay();
    }
  }

  void _resetDisplay() {
    _timer?.cancel();
    _sseSubscription?.cancel();
    setState(() {
      _entries.clear();
      _currentIndex = 0;
    });
    _startDisplay();
  }

  void _startDisplay() {
    if (widget.sessionId != null && widget.sessionId!.isNotEmpty) {
      _connectToLiveStream(widget.sessionId!);
    } else {
      _startSimulating();
    }
  }

  /// Connects to the real backend SSE stream
  Future<void> _connectToLiveStream(String sessionId) async {
    final baseUrl = 'https://muhammadahsanmask-sirena-backend.hf.space';
    final url = '$baseUrl/api/stream/$sessionId';

    try {
      final dio = Dio();
      final response = await dio.get(
        url,
        options: Options(responseType: ResponseType.stream),
      );

      final stream = response.data.stream;
      _sseSubscription = stream
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
        if (line.startsWith('data: ')) {
          try {
            final dataJson = line.substring(6);
            final event = jsonDecode(dataJson);
            if (event['type'] == 'AGENT_TRACE') {
              if (mounted) {
                setState(() {
                  _entries.add(ThoughtEntry(
                    timestamp: DateTime.now(),
                    agentName: event['agent'] ?? 'Agent',
                    message: event['thought'] ?? event['action'] ?? '',
                    type: _inferType(event),
                  ));
                });
                _scrollToBottom();
              }
            } else if (event['type'] == 'DONE') {
              _sseSubscription?.cancel();
            }
          } catch (e) {
            // Silently ignore malformed JSON or pings
          }
        }
      });
    } catch (e) {
      _startSimulating(); // Fallback if server is down
    }
  }

  ThoughtType _inferType(Map<String, dynamic> event) {
    final thought = event['thought']?.toString().toLowerCase() ?? '';
    final action = event['action']?.toString().toLowerCase() ?? '';
    if (thought.contains('critical') || action.contains('escalate')) return ThoughtType.critical;
    if (action.contains('notif') || action.contains('alert')) return ThoughtType.warning;
    if (action.contains('complete') || action.contains('success')) return ThoughtType.success;
    return ThoughtType.info;
  }

  void _startSimulating() {
    final scenarioId = DataService().getScenarioId(widget.scenario);
    final actions = DataService().getActions(scenarioId);
    
    final List<ThoughtEntry> actionThoughts = actions.expand((action) => [
      ThoughtEntry(
        timestamp: DateTime.now(), 
        agentName: 'Planning Agent', 
        message: 'Deciding: ${action.actionName}'
      ),
      ThoughtEntry(
        timestamp: DateTime.now(), 
        agentName: 'Execution Agent', 
        message: action.agentTraceNote,
        type: action.status == 'SIMULATED_SUCCESS' ? ThoughtType.success : ThoughtType.warning
      ),
    ]).toList();

    final List<ThoughtEntry> fullTrace = [
      ThoughtEntry(timestamp: DateTime.now(), agentName: 'Signal Agent', message: 'Analyzing scenario-specific signals...'),
      ThoughtEntry(timestamp: DateTime.now(), agentName: 'Detection Agent', message: 'Confirmed crisis event detected', type: ThoughtType.warning),
      ...actionThoughts,
    ];

    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (_currentIndex < fullTrace.length) {
        if (mounted) {
          setState(() {
            _entries.add(fullTrace[_currentIndex]);
            _currentIndex++;
          });
          _scrollToBottom();
        }
      } else {
        _timer?.cancel();
      }
    });
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(_scrollController.position.maxScrollExtent, duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _sseSubscription?.cancel();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_entries.isEmpty) {
      return const Center(child: CircularProgressIndicator(strokeWidth: 2, color: CIROTheme.primary));
    }
    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.all(12),
      itemCount: _entries.length,
      itemBuilder: (context, index) {
        final entry = _entries[index];
        return Padding(
          padding: const EdgeInsets.only(bottom: 8.0),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('[${entry.timestamp.hour}:${entry.timestamp.minute.toString().padLeft(2, '0')}]', style: const TextStyle(color: CIROTheme.textDim, fontFamily: 'Roboto Mono', fontSize: 10)),
              const SizedBox(width: 8),
              Expanded(
                child: RichText(
                  text: TextSpan(
                    style: const TextStyle(fontFamily: 'Roboto Mono', fontSize: 11),
                    children: [
                      TextSpan(text: '${entry.agentName} → ', style: const TextStyle(color: CIROTheme.primary, fontWeight: FontWeight.bold)),
                      TextSpan(text: entry.message, style: TextStyle(color: _getColor(entry.type))),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Color _getColor(ThoughtType type) {
    switch (type) {
      case ThoughtType.warning: return Colors.orangeAccent;
      case ThoughtType.critical: return CIROTheme.error;
      case ThoughtType.success: return CIROTheme.secondary;
      default: return CIROTheme.textBody;
    }
  }
}
