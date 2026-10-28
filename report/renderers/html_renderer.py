"""
HTML Renderer

Converts report data into HTML format for web display or PDF generation.
Supports both "summary" and "detailed" report types.
Detailed mode uses academic publication-style formatting.
"""

from datetime import datetime
from typing import Dict, Any

from report.base import Renderer
from report.styles import get_html_styles


class HTMLRenderer(Renderer):
    """Renders reports as HTML."""

    def __init__(self):
        self._section_counter = 0
        self._figure_counter = 0
        self._table_counter = 0

    def render_full_report(self, report_data: Dict[str, Any], standalone: bool = False) -> str:
        """
        Render complete report as HTML.

        Args:
            report_data: Full report data including metadata and components
            standalone: If True, include full HTML document structure

        Returns:
            Complete HTML report as string
        """
        # Reset counters for each report
        self._section_counter = 0
        self._figure_counter = 0
        self._table_counter = 0

        report_type = report_data.get('report_type', 'summary')
        css = get_html_styles(standalone=standalone, report_type=report_type)
        html_parts = []

        # Add wrapper div (academic class for detailed mode)
        if report_type == 'detailed':
            html_parts.append('<div class="unified-report academic-report">')
        else:
            html_parts.append('<div class="unified-report">')

        # Add header
        if report_type == 'detailed':
            html_parts.append(self._render_academic_header(report_data))
        else:
            html_parts.append(self.render_header(report_data))

        # Detailed mode: methodology section after header
        if report_type == 'detailed':
            html_parts.append(self._render_methodology_section(report_data))

        # Add components
        html_parts.append('<div class="report-content">')

        if 'components' in report_data:
            for component_name, component_data in report_data['components'].items():
                html_parts.append(f'<div class="report-section" data-component="{component_name}">')
                html_parts.append(self.render_component(component_name, component_data, report_type))
                html_parts.append('</div>')

        html_parts.append('</div>')

        # Detailed mode: citations section at end
        if report_type == 'detailed':
            html_parts.append(self._render_citations_section(report_data))

        html_parts.append('</div>')

        if standalone:
            # For PDF or download, include full HTML document
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Report - {report_data.get('window_title', 'Chat Session')}</title>
                <style>{css}</style>
            </head>
            <body>
                {''.join(html_parts)}
            </body>
            </html>
            """
        else:
            # For modal display, just return the styled content
            return f"<style>{css}</style>{''.join(html_parts)}"

    # ========== Summary Mode Rendering ==========

    def render_header(self, report_data: Dict[str, Any]) -> str:
        """Render report header with metadata."""
        generated_date = datetime.fromtimestamp(
            report_data.get('generated_at', 0)
        ).strftime('%B %d, %Y')

        report_type = report_data.get('report_type', 'summary')
        report_type_label = "Detailed Analysis" if report_type == "detailed" else "Summary"

        summary = report_data.get('summary', {})
        models_used = report_data.get('models_used', {})

        # Build models display
        models_html = ""
        if models_used:
            model_list = ", ".join([f"{name} ({info['provider']})" for name, info in models_used.items()])
            models_html = f"""
                <div class="meta-item">
                    <div class="meta-label">Models Used</div>
                    <div class="meta-value meta-value-models">{model_list}</div>
                </div>
            """

        return f"""
        <div class="report-header">
            <h2>{report_data.get('window_title', 'Chat Session Report')}</h2>
            <p class="report-type-badge report-type-{report_type}">{report_type_label}</p>
            {f'<p class="window-description">{report_data.get("window_description")}</p>' if report_data.get('window_description') else ''}
            <div class="report-meta">
                <div class="meta-item">
                    <div class="meta-label">Generated</div>
                    <div class="meta-value">{generated_date}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Conversations</div>
                    <div class="meta-value">{summary.get('total_conversations', 0)}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Total Messages</div>
                    <div class="meta-value">{summary.get('total_user_messages', 0) + summary.get('total_model_messages', 0)}</div>
                </div>
                {models_html}
            </div>
        </div>
        """

    def render_component(self, component_name: str, data: Dict[str, Any],
                         report_type: str = 'summary') -> str:
        """
        Render a single component's data.

        Args:
            component_name: Name of the component
            data: Component's generated data
            report_type: "summary" or "detailed"

        Returns:
            HTML string for the component
        """
        # Detailed mode uses academic rendering
        if report_type == 'detailed':
            return self._render_component_academic(component_name, data)

        # Summary mode: route to product-style renderers
        if component_name == 'ai_summary':
            return self._render_ai_summary(data)
        elif component_name == 'saved_messages':
            return self._render_saved_messages(data)
        elif component_name == 'descriptive_stats':
            return self._render_descriptive_stats(data)
        elif component_name == 'nlp_analysis':
            return self._render_nlp_analysis(data)
        elif component_name == 'cooccurrence_analysis':
            return self._render_cooccurrence_analysis(data)
        else:
            return f'<p>Unknown component: {component_name}</p>'

    def _render_ai_summary(self, data: Dict[str, Any]) -> str:
        """Render AI summary component (summary mode)."""
        summary_text = data.get('summary', 'No summary available')
        formatted_summary = self._format_text_with_breaks(summary_text)

        html = f"""
        <div class="report-component ai-summary">
            <div class="component-header">
                <h3 class="component-title">Summary</h3>
            </div>
            <div class="summary-text">{formatted_summary}</div>
        """

        if data.get('themes'):
            html += """
                <div class="themes-section">
                    <h4>Key Themes</h4>
                    <ul class="themes-list-simple">
            """
            for theme in data['themes']:
                html += f"<li>{theme}</li>"
            html += "</ul></div>"

        if data.get('progress_notes'):
            formatted_notes = self._format_text_with_breaks(data['progress_notes'])
            html += f"""
                <div class="progress-notes">
                    <h4>Progress Notes</h4>
                    <div class="progress-notes-text">{formatted_notes}</div>
                </div>
            """

        html += f"""
            <p class="generated-by">Generated with {data.get('generated_with', 'AI')}</p>
        </div>
        """
        return html

    def _render_saved_messages(self, data: Dict[str, Any]) -> str:
        """Render saved messages component (summary mode)."""
        html = f"""
        <div class="report-component saved-messages">
            <div class="component-header">
                <h3 class="component-title">Saved Messages ({data['total_count']})</h3>
            </div>
        """

        if data['selections']:
            for selection in data['selections']:
                html += f"""
                <div class="saved-message">
                    <p class="message-text">"{selection['text']}"</p>
                    {f'<p class="message-note">Note: {selection["note"]}</p>' if selection.get('note') else ''}
                    <p class="message-date">{selection['created_at_formatted']}</p>
                </div>
                """
        else:
            html += "<p class='no-data'>No saved messages</p>"

        html += "</div>"
        return html

    def _render_descriptive_stats(self, data: Dict[str, Any]) -> str:
        """Render descriptive statistics component (summary mode)."""
        html = f"""
        <div class="report-component descriptive-stats">
            <div class="component-header">
                <h3 class="component-title">Conversation Statistics</h3>
            </div>
            <div class="stats-row">
                <div class="stat-item">
                    <span class="stat-value">{data['total_messages']}</span>
                    <span class="stat-label">Messages</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value">{data['user_messages']}</span>
                    <span class="stat-label">Patient</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value">{data['assistant_messages']}</span>
                    <span class="stat-label">AI</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value">{round(data['avg_words_per_user_message'])}</span>
                    <span class="stat-label">Avg Words</span>
                </div>
            </div>
        </div>
        """
        return html

    def _render_nlp_analysis(self, data: Dict[str, Any]) -> str:
        """Render NLP analysis component (summary mode). Resilient to missing sub-feature keys."""
        html = """
        <div class="report-component nlp-analysis">
            <div class="component-header">
                <h3 class="component-title">Language Analysis</h3>
            </div>
            <div class="nlp-content">
        """

        # Sentiment (inline, no card wrapper)
        if 'average_sentiment' in data:
            sentiment_label = self._get_sentiment_label(data['average_sentiment'])
            pct = data.get('sentiment_percentages', {})
            html += f"""
                <div class="nlp-subsection">
                    <h4 class="nlp-title">Sentiment</h4>
                    <div class="sentiment-score">
                        Overall: {data['average_sentiment']:.2f} ({sentiment_label})
                    </div>
                    <div class="progress-bars">
                        <div class="progress-item">
                            <span>Positive ({pct.get('positive', 0):.0f}%)</span>
                            <div class="progress-bar">
                                <div class="progress-fill progress-positive" style="width: {pct.get('positive', 0):.0f}%"></div>
                            </div>
                        </div>
                        <div class="progress-item">
                            <span>Neutral ({pct.get('neutral', 0):.0f}%)</span>
                            <div class="progress-bar">
                                <div class="progress-fill progress-neutral" style="width: {pct.get('neutral', 0):.0f}%"></div>
                            </div>
                        </div>
                        <div class="progress-item">
                            <span>Negative ({pct.get('negative', 0):.0f}%)</span>
                            <div class="progress-bar">
                                <div class="progress-fill progress-negative" style="width: {pct.get('negative', 0):.0f}%"></div>
                            </div>
                        </div>
                    </div>
                </div>
            """

        # Voice (inline, no card wrapper)
        if 'voice_analysis' in data:
            va = data['voice_analysis']
            html += f"""
                <div class="nlp-subsection">
                    <h4 class="nlp-title">Voice</h4>
                    <div class="progress-bars">
                        <div class="progress-item">
                            <span>Active ({va.get('active_ratio', 0):.0f}%)</span>
                            <div class="progress-bar">
                                <div class="progress-fill progress-active" style="width: {va.get('active_ratio', 0):.0f}%"></div>
                            </div>
                        </div>
                        <div class="progress-item">
                            <span>Passive ({va.get('passive_ratio', 0):.0f}%)</span>
                            <div class="progress-bar">
                                <div class="progress-fill progress-passive" style="width: {va.get('passive_ratio', 0):.0f}%"></div>
                            </div>
                        </div>
                    </div>
                    <p class="nlp-note">Questions: {data.get('question_frequency', 0):.0f}% of messages</p>
                </div>
            """

        # Emotional keywords
        if 'emotional_keywords' in data:
            keywords = data['emotional_keywords']
            html += f"""
                <div class="nlp-subsection">
                    <h4 class="nlp-title">Emotional Keywords</h4>
                    <div class="keyword-counts">
                        <div class="keyword-row">
                            <span class="keyword-label">Positive</span>
                            <span class="keyword-value">{keywords.get('positive', 0)}</span>
                        </div>
                        <div class="keyword-row">
                            <span class="keyword-label">Negative</span>
                            <span class="keyword-value">{keywords.get('negative', 0)}</span>
                        </div>
                        <div class="keyword-row">
                            <span class="keyword-label">Uncertainty</span>
                            <span class="keyword-value">{keywords.get('uncertainty', 0)}</span>
                        </div>
                    </div>
                </div>
            """

        html += """
            </div>
        </div>
        """
        return html

    def _render_cooccurrence_analysis(self, data: Dict[str, Any]) -> str:
        """Render co-occurrence analysis component (summary mode)."""
        html = """
        <div class="report-component cooccurrence-analysis">
            <div class="component-header">
                <h3 class="component-title">Word Co-occurrence</h3>
            </div>
            <div class="cooccurrence-content">
        """

        if data.get('error'):
            html += f"""
                <div class="error-message">
                    <p>Error generating co-occurrence analysis: {data['error']}</p>
                </div>
            """
        elif data.get('total_unique_words', 0) == 0:
            html += """
                <p class="no-data">No word co-occurrence data available</p>
            """
        else:
            # Show network graph if available
            if data.get('has_visualization') and data.get('graph_image'):
                html += f"""
                <div class="cooccurrence-graph">
                    <img src="data:image/png;base64,{data['graph_image']}"
                         alt="Word Co-occurrence Network"
                         class="network-graph-image" />
                    <p class="graph-caption">
                        Network showing relationships between frequently co-occurring words.
                        Node size reflects word frequency; connections show co-occurrence strength.
                    </p>
                </div>
                """

            # Show statistics
            html += f"""
                <div class="cooccurrence-stats">
                    <div class="stats-row">
                        <div class="stat-item">
                            <span class="stat-value">{data['total_unique_words']}</span>
                            <span class="stat-label">Unique Words</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-value">{data['total_sentences']}</span>
                            <span class="stat-label">Sentences Analyzed</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-value">{data.get('message_count', 0)}</span>
                            <span class="stat-label">Messages</span>
                        </div>
                    </div>
                </div>
            """

            # Show top words
            if data.get('top_words'):
                html += """
                    <div class="top-words-section">
                        <h4>Most Frequent Words</h4>
                        <div class="top-words-list">
                """
                for word_data in data['top_words'][:10]:
                    html += f"""
                        <div class="word-item">
                            <span class="word-text">{word_data['word']}</span>
                            <span class="word-count">{word_data['count']}</span>
                        </div>
                    """
                html += """
                        </div>
                    </div>
                """

        html += """
            </div>
        </div>
        """
        return html

    # ========== Detailed / Academic Mode Rendering ==========

    def _render_component_academic(self, component_name: str, data: Dict[str, Any]) -> str:
        """Dispatch to academic renderers for detailed mode."""
        if component_name == 'ai_summary':
            return self._render_ai_summary_academic(data)
        elif component_name == 'saved_messages':
            return self._render_saved_messages_academic(data)
        elif component_name == 'descriptive_stats':
            return self._render_descriptive_stats_academic(data)
        elif component_name == 'nlp_analysis':
            return self._render_nlp_analysis_academic(data)
        elif component_name == 'cooccurrence_analysis':
            return self._render_cooccurrence_analysis_academic(data)
        else:
            return f'<p>Unknown component: {component_name}</p>'

    def _render_academic_header(self, report_data: Dict[str, Any]) -> str:
        """Render academic-style report header."""
        generated_date = datetime.fromtimestamp(
            report_data.get('generated_at', 0)
        ).strftime('%B %d, %Y')

        summary = report_data.get('summary', {})
        models_used = report_data.get('models_used', {})
        total_messages = (summary.get('total_user_messages', 0) +
                          summary.get('total_model_messages', 0))

        model_list = ""
        if models_used:
            model_list = ", ".join([f"{name} ({info['provider']})"
                                    for name, info in models_used.items()])

        return f"""
        <div class="report-header">
            <h2>{report_data.get('window_title', 'Conversation Analysis Report')}</h2>
            <p class="report-type-badge">Detailed Analysis Report</p>
            {f'<p class="window-description">{report_data.get("window_description")}</p>'
             if report_data.get('window_description') else ''}
            <div class="report-meta">
                <p>Generated: {generated_date} &nbsp;|&nbsp;
                   Conversations: {summary.get('total_conversations', 0)} &nbsp;|&nbsp;
                   Messages: {total_messages}
                   {f' &nbsp;|&nbsp; Models: {model_list}' if model_list else ''}</p>
            </div>
        </div>
        """

    def _render_ai_summary_academic(self, data: Dict[str, Any]) -> str:
        """Render AI summary as Executive Summary (academic mode)."""
        self._section_counter += 1
        summary_text = data.get('summary', 'No summary available')
        formatted_summary = self._format_text_with_breaks(summary_text)

        html = f"""
        <div class="report-component ai-summary">
            <div class="component-header">
                <h3 class="component-title">
                    <span class="section-number">{self._section_counter}.</span>
                    Executive Summary
                </h3>
            </div>
            <div class="summary-content">
                <div class="summary-text">{formatted_summary}</div>
        """

        if data.get('themes'):
            html += '<div class="themes-section"><h4>Key Themes</h4><ul class="themes-list-simple">'
            for theme in data['themes']:
                html += f"<li>{theme}</li>"
            html += "</ul></div>"

        if data.get('progress_notes'):
            formatted_notes = self._format_text_with_breaks(data['progress_notes'])
            html += f"""
                <div class="progress-notes">
                    <h4>Clinical Notes</h4>
                    <div class="progress-notes-text">{formatted_notes}</div>
                </div>
            """

        html += f"""
                <p class="generated-by">Generated with {data.get('generated_with', 'AI')}</p>
            </div>
        </div>
        """
        return html

    def _render_descriptive_stats_academic(self, data: Dict[str, Any]) -> str:
        """Render descriptive statistics with interpretive prose (academic mode)."""
        self._section_counter += 1
        self._table_counter += 1

        avg_words = round(data['avg_words_per_user_message'])
        duration = data['session_duration_hours']
        total = data['total_messages']
        shortest = data.get('shortest_user_message', 0)
        longest = data.get('longest_user_message', 0)

        interpretive_text = (
            f"A total of {total} messages were exchanged over a period of "
            f"{duration} hours, comprising {data['user_messages']} user messages "
            f"and {data['assistant_messages']} assistant responses. "
            f"User messages averaged {avg_words} words in length"
        )
        if longest > 0:
            interpretive_text += (
                f" (range: {shortest}\u2013{longest} words)"
            )
        interpretive_text += f", with a combined corpus of {data['total_words']:,} words."

        html = f"""
        <div class="report-component descriptive-stats">
            <div class="component-header">
                <h3 class="component-title">
                    <span class="section-number">{self._section_counter}.</span>
                    Descriptive Statistics
                </h3>
            </div>
            <div class="stats-content">
                <p class="interpretive-text">{interpretive_text}</p>
                <p class="table-caption">Table {self._table_counter}. Summary of conversation metrics.</p>
                <table class="breakdown-table">
                    <thead><tr>
                        <th>Metric</th><th>Value</th>
                    </tr></thead>
                    <tbody>
                        <tr><td>Total Messages</td><td>{total}</td></tr>
                        <tr><td>User Messages</td><td>{data['user_messages']}</td></tr>
                        <tr><td>Assistant Messages</td><td>{data['assistant_messages']}</td></tr>
                        <tr><td>Session Duration (hours)</td><td>{duration}</td></tr>
                        <tr><td>Mean Words per User Message</td><td>{avg_words}</td></tr>
                        <tr><td>Total Word Count</td><td>{data['total_words']:,}</td></tr>
                        <tr><td>Longest User Message (words)</td><td>{longest}</td></tr>
                        <tr><td>Shortest User Message (words)</td><td>{shortest}</td></tr>
                    </tbody>
                </table>
        """

        # Messages by day table
        if data.get('messages_by_day'):
            self._table_counter += 1
            html += f"""
                <p class="table-caption">Table {self._table_counter}. Message distribution by day.</p>
                <table class="breakdown-table">
                    <thead><tr>
                        <th>Date</th><th>User</th><th>Assistant</th><th>Total</th>
                    </tr></thead>
                    <tbody>
            """
            for date_str, counts in sorted(data['messages_by_day'].items()):
                user_count = counts.get('user', 0)
                assistant_count = counts.get('assistant', 0)
                html += f"""
                    <tr>
                        <td>{date_str}</td><td>{user_count}</td>
                        <td>{assistant_count}</td><td>{user_count + assistant_count}</td>
                    </tr>
                """
            html += "</tbody></table>"

        html += "</div></div>"
        return html

    def _render_nlp_analysis_academic(self, data: Dict[str, Any]) -> str:
        """Render NLP analysis with interpretive prose and subsections (academic mode)."""
        self._section_counter += 1
        section_num = self._section_counter
        sub_idx = 0

        html = f"""
        <div class="report-component nlp-analysis">
            <div class="component-header">
                <h3 class="component-title">
                    <span class="section-number">{section_num}.</span>
                    Linguistic Analysis
                </h3>
            </div>
            <div class="nlp-content">
        """

        # Sentiment sub-section
        if 'average_sentiment' in data:
            sub_idx += 1
            sentiment = data['average_sentiment']
            label = self._get_sentiment_label(sentiment)
            pct = data.get('sentiment_percentages', {})

            html += f"""
                <h4>{section_num}.{sub_idx} Sentiment Analysis</h4>
                <p class="interpretive-text">
                    Sentiment analysis revealed a mean polarity score of {sentiment:.2f}
                    ({label.lower()}). Of the messages analyzed,
                    {pct.get('positive', 0):.1f}% were classified as positive,
                    {pct.get('neutral', 0):.1f}% as neutral, and
                    {pct.get('negative', 0):.1f}% as negative.
                </p>
                <div class="progress-bars">
                    <div class="progress-item">
                        <span>Positive ({pct.get('positive', 0):.0f}%)</span>
                        <div class="progress-bar">
                            <div class="progress-fill progress-positive"
                                 style="width: {pct.get('positive', 0):.0f}%"></div>
                        </div>
                    </div>
                    <div class="progress-item">
                        <span>Neutral ({pct.get('neutral', 0):.0f}%)</span>
                        <div class="progress-bar">
                            <div class="progress-fill progress-neutral"
                                 style="width: {pct.get('neutral', 0):.0f}%"></div>
                        </div>
                    </div>
                    <div class="progress-item">
                        <span>Negative ({pct.get('negative', 0):.0f}%)</span>
                        <div class="progress-bar">
                            <div class="progress-fill progress-negative"
                                 style="width: {pct.get('negative', 0):.0f}%"></div>
                        </div>
                    </div>
                </div>
            """

        # Voice sub-section
        if 'voice_analysis' in data:
            sub_idx += 1
            va = data['voice_analysis']
            html += f"""
                <h4>{section_num}.{sub_idx} Voice Analysis</h4>
                <p class="interpretive-text">
                    Active voice was used in {va.get('active_ratio', 0):.1f}% of
                    verb instances, while passive constructions accounted for
                    {va.get('passive_ratio', 0):.1f}%
                    (N = {va.get('total_verbs', 0)} total verbs).
                    Questions appeared in {data.get('question_frequency', 0):.1f}% of user messages.
                </p>
            """

        # Emotional keywords sub-section
        if 'emotional_keywords' in data:
            sub_idx += 1
            keywords = data['emotional_keywords']
            self._table_counter += 1
            html += f"""
                <h4>{section_num}.{sub_idx} Emotional Keywords</h4>
                <p class="table-caption">Table {self._table_counter}. Emotional keyword frequency counts.</p>
                <table class="breakdown-table">
                    <thead><tr><th>Category</th><th>Count</th></tr></thead>
                    <tbody>
                        <tr><td>Positive</td><td>{keywords.get('positive', 0)}</td></tr>
                        <tr><td>Negative</td><td>{keywords.get('negative', 0)}</td></tr>
                        <tr><td>Uncertainty</td><td>{keywords.get('uncertainty', 0)}</td></tr>
                    </tbody>
                </table>
            """

        html += "</div></div>"
        return html

    def _render_cooccurrence_analysis_academic(self, data: Dict[str, Any]) -> str:
        """Render co-occurrence analysis with figure captions and ranked table (academic mode)."""
        self._section_counter += 1

        html = f"""
        <div class="report-component cooccurrence-analysis">
            <div class="component-header">
                <h3 class="component-title">
                    <span class="section-number">{self._section_counter}.</span>
                    Word Co-occurrence Analysis
                </h3>
            </div>
            <div class="cooccurrence-content">
        """

        if data.get('error'):
            html += f'<p class="interpretive-text">Error: {data["error"]}</p>'
        elif data.get('total_unique_words', 0) == 0:
            html += '<p class="interpretive-text">Insufficient data for co-occurrence analysis.</p>'
        else:
            html += f"""
                <p class="interpretive-text">
                    Co-occurrence analysis was conducted on {data.get('message_count', 0)} user messages
                    containing {data['total_unique_words']} unique words across
                    {data['total_sentences']} sentences.
                </p>
            """

            # Figure with caption
            if data.get('has_visualization') and data.get('graph_image'):
                self._figure_counter += 1
                html += f"""
                <div class="figure-container">
                    <img src="data:image/png;base64,{data['graph_image']}"
                         alt="Word Co-occurrence Network"
                         class="network-graph-image" />
                    <p class="figure-caption">
                        <em>Figure {self._figure_counter}.</em> Word co-occurrence network.
                        Node size reflects word frequency; edge weight indicates
                        co-occurrence strength within sentences.
                    </p>
                </div>
                """

            # Top words as ranked table
            if data.get('top_words'):
                self._table_counter += 1
                html += f"""
                    <p class="table-caption">Table {self._table_counter}. Most frequent words by occurrence count.</p>
                    <table class="breakdown-table">
                        <thead><tr><th>Rank</th><th>Word</th><th>Frequency</th></tr></thead>
                        <tbody>
                """
                for rank, word_data in enumerate(data['top_words'][:10], 1):
                    html += f"""
                        <tr>
                            <td>{rank}</td>
                            <td>{word_data['word']}</td>
                            <td>{word_data['count']}</td>
                        </tr>
                    """
                html += "</tbody></table>"

        html += "</div></div>"
        return html

    def _render_saved_messages_academic(self, data: Dict[str, Any]) -> str:
        """Render saved messages as numbered selections (academic mode)."""
        self._section_counter += 1

        html = f"""
        <div class="report-component saved-messages">
            <div class="component-header">
                <h3 class="component-title">
                    <span class="section-number">{self._section_counter}.</span>
                    Selected Messages (N = {data['total_count']})
                </h3>
            </div>
            <div class="messages-content">
        """

        if data['selections']:
            for i, selection in enumerate(data['selections'], 1):
                html += f"""
                <div class="saved-message">
                    <p class="message-text">[{i}] \"{selection['text']}\"</p>
                    {f'<p class="message-note">Note: {selection["note"]}</p>'
                     if selection.get('note') else ''}
                    <p class="message-date">{selection['created_at_formatted']}</p>
                </div>
                """
        else:
            html += '<p class="no-data">No saved messages.</p>'

        html += "</div></div>"
        return html

    # ========== Shared Sections (Detailed Mode Only) ==========

    def _render_methodology_section(self, report_data: Dict[str, Any]) -> str:
        """Render methodology section (detailed mode only)."""
        from report.registry import get_registry
        registry = get_registry()

        active_components = set(report_data.get('components', {}).keys())
        methods = []
        seen = set()

        for _key, meta in registry.get_all_features().items():
            if meta.component_key in active_components and meta.citation and meta.status == "available":
                if meta.citation not in seen:
                    methods.append((meta.name, meta.description, meta.citation))
                    seen.add(meta.citation)

        if not methods:
            return ""

        self._section_counter += 1

        # Build descriptive methodology as prose
        method_descriptions = []
        for name, description, citation in methods:
            method_descriptions.append(
                f"<strong>{name}</strong> ({citation}): {description}"
            )
        methods_prose = ". ".join(method_descriptions) + "."

        return f"""
        <div class="report-section methodology-section">
            <div class="component-header">
                <h3 class="component-title">
                    <span class="section-number">{self._section_counter}.</span>
                    Methodology
                </h3>
            </div>
            <p class="interpretive-text">
                This report employs the following analysis methods: {methods_prose}
            </p>
        </div>
        """

    def _render_citations_section(self, report_data: Dict[str, Any]) -> str:
        """Render citations footer (detailed mode only)."""
        from report.registry import get_registry
        registry = get_registry()

        active_components = set(report_data.get('components', {}).keys())
        citations = set()

        for _key, meta in registry.get_all_features().items():
            if meta.component_key in active_components and meta.citation and meta.status == "available":
                citations.add(meta.citation)

        if not citations:
            return ""

        self._section_counter += 1
        items_html = "".join(f"<li>{c}</li>" for c in sorted(citations))

        return f"""
        <div class="report-section citations-section">
            <div class="component-header">
                <h3 class="component-title">
                    <span class="section-number">{self._section_counter}.</span>
                    References
                </h3>
            </div>
            <ol class="citations-list">{items_html}</ol>
        </div>
        """

    # ========== Helpers ==========

    def _get_sentiment_label(self, score: float) -> str:
        """Get sentiment label from score."""
        if score > 0.3:
            return "Positive"
        elif score < -0.3:
            return "Negative"
        else:
            return "Neutral"

    def _format_text_with_breaks(self, text: str) -> str:
        """Format text with proper HTML paragraph breaks."""
        import re

        if not text:
            return ""

        # Split text into sentences (rough approximation)
        sentences = re.split(r'(?<=[.!?])\s+', text)

        # Group sentences into paragraphs (roughly 3-4 sentences per paragraph)
        paragraphs = []
        current_para = []
        sentence_count = 0

        for sentence in sentences:
            current_para.append(sentence)
            sentence_count += 1

            # Create paragraph break every 3-4 sentences
            if sentence_count >= 3:
                paragraphs.append(' '.join(current_para))
                current_para = []
                sentence_count = 0

        # Add remaining sentences
        if current_para:
            paragraphs.append(' '.join(current_para))

        # Convert to HTML paragraphs
        html_paragraphs = [f'<p>{para}</p>' for para in paragraphs if para.strip()]

        return '\n'.join(html_paragraphs)
