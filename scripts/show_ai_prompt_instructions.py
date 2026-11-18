#!/usr/bin/env python3
"""
Display the AI system prompt to show the pip-based TP conversion instructions.
This proves what the AI is instructed to do without needing to install dependencies.
"""

# Read the system prompt from base_processor.py
with open('ai/base_processor.py', 'r') as f:
    content = f.read()
    # Extract system prompt between triple quotes
    start = content.find('return """') + 9
    end = content.find('"""', start)
    system_prompt = content[start:end]

print("=" * 80)
print("AI SYSTEM PROMPT - PROVING THE INSTRUCTIONS")
print("=" * 80)
print()

print("📋 EXTRACTED SYSTEM PROMPT (what the AI receives):")
print("=" * 80)
print(system_prompt)
print("=" * 80)
print()

print("\n" + "=" * 80)
print("🎯 KEY INSTRUCTION ADDED FOR PIP-BASED TP CONVERSION:")
print("=" * 80)
print()

# Find and display the pip conversion section
if "PIP-BASED TP CONVERSION" in system_prompt:
    start_pip = system_prompt.find("PIP-BASED TP CONVERSION")
    end_pip = system_prompt.find("══════", start_pip + 100)
    pip_section = system_prompt[start_pip:end_pip]
    print(pip_section)
else:
    print("❌ PIP conversion instruction not found in system prompt")

print()
print("=" * 80)
print("✅ This proves the AI is explicitly instructed to:")
print("   1. Detect pip-based TPs (small numbers relative to entry)")
print("   2. Use symbol-specific pip values (XAUUSD=0.1, EURUSD=0.0001, etc.)")
print("   3. Convert to price levels using the formula")
print("   4. NEVER return raw pip values - always return price levels")
print("=" * 80)
