import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class CIROTheme {
  static const Color background = Color(0xFF0A0E14);
  static const Color surface = Color(0xFF141A23);
  static const Color primary = Color(0xFFFF9F1C); // Hazard Orange
  static const Color secondary = Color(0xFF2EC4B6); // Signal Teal
  static const Color error = Color(0xFFE71D36); // Urgent Red
  static const Color textBody = Color(0xFFE0E0E0);
  static const Color textDim = Color(0xFF9E9E9E);

  static ThemeData darkTheme = ThemeData(
    brightness: Brightness.dark,
    scaffoldBackgroundColor: background,
    primaryColor: primary,
    cardColor: surface,
    textTheme: GoogleFonts.interTextTheme(
      const TextTheme(
        headlineMedium: TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.bold,
          letterSpacing: 1.2,
        ),
        bodyLarge: TextStyle(color: textBody),
        bodySmall: TextStyle(color: textDim),
      ),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: background,
      elevation: 0,
    ),
    colorScheme: const ColorScheme.dark(
      primary: primary,
      secondary: secondary,
      error: error,
      surface: surface,
      background: background,
    ),
  );
}
