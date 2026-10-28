#!/usr/bin/env python3
"""
Manual Report Generation Script
================================
This script generates and downloads an HTML report for a specific chat window.

Usage:
    python scripts/generate_report.py

Configuration:
    Set WINDOW_ID below to the chat window you want to generate a report for.
"""

import sys
import os
from datetime import datetime

# Add parent directory to path so we can import from llm_chat
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============================================================================
# CONFIGURATION - Change this to your desired window ID
# ============================================================================
WINDOW_ID = 5  # Window ID 5: "Week 1 Anxiety" (82 messages, 2 conversations)
# ============================================================================

def main():
    """Generate and save HTML report for the specified window"""

    # Import after path is set up
    from llm_chat import create_app
    from report.generator import UnifiedReportGenerator

    print(f"Generating report for Chat Window ID: {WINDOW_ID}")
    print("=" * 60)

    # Create Flask app context
    app = create_app()

    with app.app_context():
        try:
            # Create report generator
            generator = UnifiedReportGenerator(WINDOW_ID)

            # Get window info for filename
            window = generator.window
            print(f"Window Title: {window.title}")
            print(f"Description: {window.description or 'None'}")
            print()

            # Generate the report data
            print("Generating report data...")
            report_data = generator.generate()

            # Get summary stats
            summary = report_data.get('summary', {})
            print(f"Total Conversations: {summary.get('total_conversations', 0)}")
            print(f"Total Messages: {summary.get('total_user_messages', 0) + summary.get('total_model_messages', 0)}")
            print()

            # Generate HTML
            print("Rendering HTML...")
            html_content = generator.render_html(report_data, standalone=True)

            # Create filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"report_window_{WINDOW_ID}_{timestamp}.html"

            # Save to current directory
            output_path = os.path.join(os.getcwd(), filename)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            print("✓ Report saved successfully!")
            print(f"Location: {output_path}")
            print()
            print("You can now open this HTML file in your browser.")

        except ValueError as e:
            print(f"Error: {e}")
            print(f"Please check that window ID {WINDOW_ID} exists in the database.")
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == "__main__":
    main()
