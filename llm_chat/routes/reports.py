import json
import tempfile
from flask import Blueprint, jsonify, abort, request, send_file
from flask_login import login_required, current_user
from ..models import Report, ChatWindow
from ..services.report_utils import generate_report_for_window, finalize_expired_windows
from ..utils.settings_resolution import get_effective_setting
from report.generator import UnifiedReportGenerator

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")


@reports_bp.route("/", methods=["GET"])
@login_required
def get_reports():
    """Get reports accessible to current user (only from visible windows).
    Returns only summary/default reports to avoid duplicates now that
    both summary and detailed are generated per window.
    """
    summary_filter = Report.report_type.in_(['summary', 'default'])

    if current_user.is_patient():
        reports = Report.query.join(ChatWindow).filter(
            Report.patient_id == current_user.id,
            ChatWindow.visible == True,
            summary_filter
        ).order_by(Report.generated_at.desc()).all()
    elif current_user.is_provider():
        reports = Report.query.join(ChatWindow).filter(
            Report.provider_id == current_user.id,
            ChatWindow.visible == True,
            summary_filter
        ).order_by(Report.generated_at.desc()).all()
    elif current_user.is_admin():
        reports = Report.query.join(ChatWindow).filter(
            ChatWindow.visible == True,
            summary_filter
        ).order_by(Report.generated_at.desc()).all()
    else:
        abort(403)

    return jsonify([r.to_dict() for r in reports])


@reports_bp.route("/<int:report_id>", methods=["GET"])
@login_required
def get_report(report_id):
    """Get a specific report"""
    report = Report.query.get_or_404(report_id)

    # Access control
    if current_user.is_patient() and report.patient_id != current_user.id:
        abort(403)
    elif current_user.is_provider() and report.provider_id != current_user.id:
        abort(403)

    return jsonify(report.to_dict())


@reports_bp.route("/patient/<int:patient_id>", methods=["GET"])
@login_required
def get_patient_reports(patient_id):
    """Get all reports for a specific patient (provider only, visible windows only)"""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)

    # Verify provider can access this patient
    if current_user.is_provider() and not current_user.can_access_patient(patient_id):
        abort(403)

    reports = Report.query.join(ChatWindow).filter(
        Report.patient_id == patient_id,
        ChatWindow.visible == True,
        Report.report_type.in_(['summary', 'default'])
    ).order_by(Report.generated_at.desc()).all()
    return jsonify([r.to_dict() for r in reports])


@reports_bp.route("/window/<int:window_id>", methods=["GET"])
@login_required
def get_window_report(window_id):
    """Get report for a specific window"""
    window = ChatWindow.query.get_or_404(window_id)

    # Access control
    if current_user.is_patient() and window.patient_id != current_user.id:
        abort(403)
    elif current_user.is_provider() and window.provider_id != current_user.id:
        abort(403)

    # Return summary report by default; use ?type=detailed for detailed
    requested_type = request.args.get('type', 'summary')
    report = Report.query.filter_by(window_id=window_id, report_type=requested_type).first()
    # Fallback to any report (handles legacy 'default' type)
    if not report:
        report = Report.query.filter_by(window_id=window_id).order_by(Report.generated_at.desc()).first()

    if not report:
        return jsonify({'error': 'Report not found'}), 404

    return jsonify(report.to_dict())


@reports_bp.route("/window/<int:window_id>/generate", methods=["POST"])
@login_required
def generate_window_report(window_id):
    """Manually generate a report for a window (provider only)"""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)

    window = ChatWindow.query.get_or_404(window_id)

    # Verify provider owns this window
    if current_user.is_provider() and window.provider_id != current_user.id:
        abort(403)

    if not get_effective_setting('enable_nlp_report', window.provider_id, True):
        return jsonify({'error': 'NLP reports are disabled for this provider'}), 403

    try:
        data = request.json or {}
        report_type = data.get('report_type', None)
        report = generate_report_for_window(window_id, report_type=report_type)
        return jsonify(report.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@reports_bp.route("/check-scheduler", methods=["POST"])
@login_required
def check_scheduler():
    """Manually trigger report generation for any expired windows (admin/provider only)"""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)

    try:
        processed = finalize_expired_windows()
        return jsonify({
            'status': 'success',
            'message': f'Processed {len(processed)} expired window(s)',
            'window_ids': processed
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@reports_bp.route("/html/<int:report_id>", methods=["GET"])
@login_required
def get_report_html(report_id):
    """Get formatted HTML version of a report"""
    report = Report.query.get_or_404(report_id)

    # Access control
    if current_user.is_patient() and report.patient_id != current_user.id:
        abort(403)
    elif current_user.is_provider() and report.provider_id != current_user.id:
        abort(403)

    report_data = json.loads(report.report_data)

    # Always use unified generator for rendering
    generator = UnifiedReportGenerator(report.window_id)
    html_content = generator.render_html(report_data)

    return jsonify({'html': html_content})


# Enhanced report endpoint removed - use unified endpoint instead


@reports_bp.route("/window/<int:window_id>/config", methods=["GET", "PUT"])
@login_required
def window_report_config(window_id):
    """Get or update report configuration for a window"""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)

    window = ChatWindow.query.get_or_404(window_id)

    # Verify provider owns this window
    if current_user.is_provider() and window.provider_id != current_user.id:
        abort(403)

    if request.method == "GET":
        return jsonify(window.get_report_config())

    elif request.method == "PUT":
        try:
            from ..extensions import db
            from report.registry import get_registry
            data = request.json or {}
            config = data.get('config', {})

            # Handle both v1 (flat) and v2 (hierarchical) config formats
            if config.get('version') == 2:
                # v2: validate feature keys against registry
                registry = get_registry()
                features = config.get('features', {})
                config['features'] = registry.validate_config(features)
            else:
                # v1: validate with registry-based key set plus legacy keys
                registry = get_registry()
                valid_keys = set(registry.get_available_feature_keys())
                valid_keys.add('nlp_analysis')  # legacy v1 key
                config = {k: v for k, v in config.items() if k in valid_keys}

            window.set_report_config(config)
            db.session.commit()

            return jsonify({'status': 'success', 'config': window.get_report_config()})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@reports_bp.route("/window/<int:window_id>/generate-unified", methods=["POST"])
@login_required
def generate_unified_window_report(window_id):
    """Generate a unified report using the new architecture"""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)

    window = ChatWindow.query.get_or_404(window_id)

    # Verify provider owns this window
    if current_user.is_provider() and window.provider_id != current_user.id:
        abort(403)

    if not get_effective_setting('enable_nlp_report', window.provider_id, True):
        return jsonify({'error': 'NLP reports are disabled for this provider'}), 403

    try:
        report = generate_report_for_window(window_id)
        return jsonify(report.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@reports_bp.route("/download/<int:report_id>/<format>", methods=["GET"])
@login_required
def download_report(report_id, format):
    """Download report in specified format (html or pdf)"""
    report = Report.query.get_or_404(report_id)

    # Access control
    if current_user.is_patient() and report.patient_id != current_user.id:
        abort(403)
    elif current_user.is_provider() and report.provider_id != current_user.id:
        abort(403)

    return _send_report_download(report, format)


@reports_bp.route("/download/window/<int:window_id>/<report_type>/<format>", methods=["GET"])
@login_required
def download_window_report(window_id, report_type, format):
    """Download report by window ID and report type (summary or detailed)."""
    window = ChatWindow.query.get_or_404(window_id)

    # Access control
    if current_user.is_patient() and window.patient_id != current_user.id:
        abort(403)
    elif current_user.is_provider() and window.provider_id != current_user.id:
        abort(403)

    if report_type not in ('summary', 'detailed'):
        abort(400, "report_type must be 'summary' or 'detailed'")

    report = Report.query.filter_by(window_id=window_id, report_type=report_type).first()
    if not report:
        # Fallback: generate on the fly if not stored yet
        report = Report.query.filter_by(window_id=window_id).first()
    if not report:
        abort(404, "No report found for this window")

    return _send_report_download(report, format)


def _send_report_download(report, format):
    """Shared helper to send a report download in the requested format."""
    window = ChatWindow.query.get(report.window_id)
    report_data = json.loads(report.report_data)
    rt = report_data.get('report_type', 'summary')
    slug = window.title.replace(' ', '_')
    filename = f"report_{slug}_{rt}.{format}"

    if format == 'html':
        html_content = UnifiedReportGenerator.export_html_from_data(report.window_id, report_data)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            f.write(html_content)
            temp_path = f.name

        return send_file(
            temp_path,
            as_attachment=True,
            download_name=filename,
            mimetype='text/html'
        )

    elif format == 'pdf':
        try:
            pdf_bytes = UnifiedReportGenerator.export_pdf_from_data(report.window_id, report_data)

            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
                f.write(pdf_bytes)
                temp_path = f.name

            return send_file(
                temp_path,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )
        except ImportError:
            # Fallback to HTML if weasyprint not available
            html_content = UnifiedReportGenerator.export_html_from_data(report.window_id, report_data)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                f.write(html_content)
                temp_path = f.name

            return send_file(
                temp_path,
                as_attachment=True,
                download_name=filename.replace('.pdf', '.html'),
                mimetype='text/html'
            )

    else:
        abort(400, "Invalid format. Use 'html' or 'pdf'")


@reports_bp.route("/live/<int:window_id>", methods=["GET"])
@login_required
def get_live_report(window_id):
    """Generate and return a live report without saving to database"""
    window = ChatWindow.query.get_or_404(window_id)

    # Access control
    if current_user.is_patient() and window.patient_id != current_user.id:
        abort(403)
    elif current_user.is_provider() and window.provider_id != current_user.id:
        abort(403)

    try:
        generator = UnifiedReportGenerator(window_id)
        report_data = generator.generate()
        html_content = generator.render_html(report_data)

        return jsonify({
            'html': html_content,
            'data': report_data,
            'window_id': window_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@reports_bp.route("/registry", methods=["GET"])
@login_required
def get_feature_registry():
    """Get the feature registry schema for UI rendering."""
    from report.registry import get_registry
    registry = get_registry()
    return jsonify({
        'groups': registry.to_ui_schema(),
        'report_types': [
            {"key": "summary", "name": "Summary", "description": "Concise overview of key findings"},
            {"key": "detailed", "name": "Detailed", "description": "Comprehensive analysis with methodology and citations"},
        ]
    })


@reports_bp.route("/capabilities", methods=["GET"])
@login_required
def get_report_capabilities():
    """Get available report capabilities (like PDF generation)"""
    from report.generator import WEASYPRINT_AVAILABLE

    return jsonify({
        'pdf_generation': WEASYPRINT_AVAILABLE,
        'html_export': True,
        'json_export': True
    })
