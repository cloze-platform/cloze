"""
PDF Renderer

Extends HTML renderer with PDF-specific optimizations for print layout.
"""

from typing import Dict, Any

from .html_renderer import HTMLRenderer, _e
from report.styles import get_pdf_styles


class PDFRenderer(HTMLRenderer):
    """Renders reports optimized for PDF generation."""

    def render_full_report(self, report_data: Dict[str, Any], standalone: bool = True) -> str:
        """
        Render complete report as HTML optimized for PDF.

        Args:
            report_data: Full report data including metadata and components
            standalone: Always True for PDF (needs full document)

        Returns:
            PDF-optimized HTML as string
        """
        # Reset counters for each report
        self._section_counter = 0
        self._figure_counter = 0
        self._table_counter = 0

        report_type = report_data.get('report_type', 'summary')
        css = get_pdf_styles(report_type=report_type)
        html_parts = []

        # Wrapper class: academic for detailed, standard for summary
        if report_type == 'detailed':
            html_parts.append('<div class="unified-report print-mode academic-report">')
        else:
            html_parts.append('<div class="unified-report print-mode">')

        # Header: academic for detailed, standard for summary
        if report_type == 'detailed':
            html_parts.append(self._render_academic_header(report_data))
        else:
            html_parts.append(self.render_header(report_data))

        # Detailed mode: methodology section
        if report_type == 'detailed':
            html_parts.append(self._render_methodology_section(report_data))

        html_parts.append('<div class="report-content">')
        if 'components' in report_data:
            for component_name, component_data in report_data['components'].items():
                html_parts.append(
                    f'<div class="report-section print-section" data-component="{component_name}">'
                )
                html_parts.append(self.render_component(component_name, component_data, report_type))
                html_parts.append('</div>')

        html_parts.append('</div>')

        # Detailed mode: citations section
        if report_type == 'detailed':
            html_parts.append(self._render_citations_section(report_data))

        html_parts.append('</div>')

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Report - {_e(report_data.get('window_title', 'Chat Session'))}</title>
            <style>{css}</style>
        </head>
        <body>
            {''.join(html_parts)}
        </body>
        </html>
        """
