import 'package:flutter/material.dart';
import 'package:ciro/theme/app_theme.dart';

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:ciro/repositories/crisis_repository.dart';
import 'package:ciro/blocs/crisis_bloc.dart';
import 'package:ciro/blocs/agent_bloc.dart';
import 'package:ciro/router/app_router.dart';
import 'package:ciro/services/firebase_service.dart';

import 'package:ciro/services/data_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await FirebaseService().initialize();
  await DataService().loadDatasets();
  runApp(const CIROApp());
}

class CIROApp extends StatelessWidget {
  const CIROApp({super.key});

  @override
  Widget build(BuildContext context) {
    return RepositoryProvider(
      create: (context) => CrisisRepository(),
      child: MultiBlocProvider(
        providers: [
          BlocProvider(
            create: (context) => CrisisBloc(
              repository: context.read<CrisisRepository>(),
            ),
          ),
          BlocProvider(
            create: (context) => AgentBloc(),
          ),
        ],
        child: MaterialApp.router(
          title: 'SIRENA',
          debugShowCheckedModeBanner: false,
          theme: CIROTheme.darkTheme,
          routerConfig: AppRouter.router,
        ),
      ),
    );
  }
}
