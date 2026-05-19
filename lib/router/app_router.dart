import 'package:go_router/go_router.dart';
import 'package:ciro/screens/dashboard_screen.dart';
import 'package:ciro/screens/agent_trace_screen.dart';
import 'package:ciro/screens/crisis_map_screen.dart';
import 'package:ciro/screens/response_plan_screen.dart';
import 'package:ciro/screens/outcome_screen.dart';

class AppRouter {
  static final router = GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(
        path: '/',
        builder: (context, state) => const DashboardScreen(),
      ),
      GoRoute(
        path: '/trace/:sessionId',
        builder: (context, state) {
          final sessionId = state.pathParameters['sessionId']!;
          return AgentTraceScreen(sessionId: sessionId);
        },
      ),
      GoRoute(
        path: '/map/:sessionId',
        builder: (context, state) {
          final sessionId = state.pathParameters['sessionId']!;
          return CrisisMapScreen(sessionId: sessionId);
        },
      ),
      GoRoute(
        path: '/plan/:sessionId',
        builder: (context, state) {
          final sessionId = state.pathParameters['sessionId']!;
          return ResponsePlanScreen(sessionId: sessionId);
        },
      ),
      GoRoute(
        path: '/outcome/:sessionId',
        builder: (context, state) {
          final sessionId = state.pathParameters['sessionId']!;
          return OutcomeScreen(sessionId: sessionId);
        },
      ),
    ],
  );
}
