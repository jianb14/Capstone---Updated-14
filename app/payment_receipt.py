"""A printable digital receipt; payment eligibility is enforced by the view."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from django.contrib.staticfiles import finders
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_payment_receipt(payment, event_time):
    booking = payment.booking
    receipt_id = f"PAY-{payment.id:06d}"
    ink, muted, line = colors.HexColor('#202020'), colors.HexColor('#737373'), colors.HexColor('#e3e3e3')
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=50, rightMargin=50,
                            topMargin=151, bottomMargin=108,
                            title=f"Payment Receipt | {receipt_id}", author="Balloorina.ph")
    width = A4[0] - 100
    body = ParagraphStyle('ReceiptBody', fontName='Helvetica', fontSize=9, leading=13,
                          textColor=ink, splitLongWords=True)
    label_style = ParagraphStyle('ReceiptLabel', parent=body, textColor=muted, fontSize=8)
    section_style = ParagraphStyle('ReceiptSection', parent=body, fontName='Helvetica-Bold',
                                  fontSize=9, spaceBefore=16, spaceAfter=8)
    hero_style = ParagraphStyle('ReceiptHero', parent=body, alignment=TA_CENTER, textColor=colors.white)
    amount_style = ParagraphStyle('ReceiptAmount', parent=hero_style, fontName='Helvetica-Bold',
                                 fontSize=30, leading=38, spaceBefore=4, spaceAfter=4)

    def para(value, style=body):
        return Paragraph(escape(str(value or '-')).replace('\n', '<br/>'), style)

    def timestamp(value):
        if not value:
            return '-'
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime('%b %d, %Y · %I:%M %p')

    def header_footer(canvas, document):
        canvas.saveState()
        height = A4[1]
        logo_path = finders.find('images/BalloorinaBlack.png') or Path(settings.BASE_DIR) / 'static/images/BalloorinaBlack.png'
        if Path(logo_path).is_file():
            logo = ImageReader(str(logo_path))
            logo_width = 125
            logo_height = logo_width * logo.getSize()[1] / logo.getSize()[0]
            canvas.drawImage(logo, 50, height - 40 - logo_height, logo_width, logo_height, mask='auto', anchor='sw')
        else:
            canvas.setFont('Helvetica-Bold', 20)
            canvas.drawString(50, height - 60, 'Balloorina.ph')
        canvas.setFillColor(ink)
        canvas.setFont('Helvetica-Bold', 16)
        canvas.drawString(50, height - 100, 'Payment Receipt')
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(muted)
        canvas.drawString(50, height - 117, 'Balloorina.ph - Official Billing Statement')
        canvas.drawRightString(A4[0] - 50, height - 52, receipt_id)
        canvas.setStrokeColor(line)
        canvas.setLineWidth(.6)
        canvas.line(50, height - 135, A4[0] - 50, height - 135)
        canvas.setDash(2, 3)
        canvas.line(50, 93, A4[0] - 50, 93)
        canvas.setDash()
        canvas.setFillColor(ink)
        canvas.setFont('Helvetica-Bold', 8)
        canvas.drawString(50, 77, 'Thank you for choosing Balloorina.ph!')
        canvas.setFillColor(muted)
        canvas.setFont('Helvetica', 7)
        canvas.drawString(50, 64, 'Keep this receipt for your payment records and event verification.')
        canvas.drawString(50, 51, 'balloorina.ph@gmail.com | +63 967 233 6222')
        canvas.drawRightString(A4[0] - 50, 51, f'Page {document.page}')
        canvas.restoreState()

    verified = payment.payment_status == 'verified'
    hero = Table([[[para('PAYMENT VERIFIED' if verified else payment.get_payment_status_display().upper(), hero_style),
                    para(f'PHP {payment.amount:,.2f}', amount_style),
                    para('Amount paid' if verified else 'Amount submitted', hero_style)]]], colWidths=[width])
    hero.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), ink),
                             ('TOPPADDING', (0, 0), (-1, -1), 17),
                             ('BOTTOMPADDING', (0, 0), (-1, -1), 17)]))
    story = [hero]

    def details(title, rows):
        story.append(Paragraph(title, section_style))
        table = Table([[para(label, label_style), para(value)] for label, value in rows],
                      colWidths=[132, width - 132], hAlign='LEFT')
        table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                   ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                   ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                                   ('TOPPADDING', (0, 0), (-1, -1), 5),
                                   ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                                   ('LINEBELOW', (0, 0), (-1, -1), .4, line)]))
        story.append(table)

    transaction_rows = [
        ('Receipt number', receipt_id),
        ('Customer', booking.user.get_full_name() or booking.user.username),
        ('Payment method', payment.get_payment_method_display()),
        ('Payment type', payment.get_payment_type_display()),
        ('Transaction reference', payment.transaction_ref or '-'),
    ]
    if payment.gcash_reference_number:
        transaction_rows.append(('GCash reference', payment.gcash_reference_number))
    if payment.gcash_sender_name:
        transaction_rows.append(('GCash sender', payment.gcash_sender_name))
    transaction_rows.append(('Date submitted', timestamp(payment.created_at)))
    if payment.paid_at:
        transaction_rows.append(('Date verified', timestamp(payment.paid_at)))
    if payment.change_request_id:
        transaction_rows.append(('Booking change request', f'#{payment.change_request_id}'))
    details('TRANSACTION DETAILS', transaction_rows)
    details('BOOKING SUMMARY', [
        ('Booking number', f'#{booking.id}'),
        ('Event', booking.event_type or '-'),
        ('Event date & time', f'{booking.event_date:%b %d, %Y} · {event_time}'),
        ('Package / extras', booking.package_type or '-'),
        ('Total booking price', f'PHP {booking.total_price:,.2f}'),
    ])
    story.append(Spacer(1, 12))
    story.append(para('This receipt acknowledges only the payment amount shown above, which may differ from the total booking price.', label_style))
    story.append(Spacer(1, 5))
    story.append(para('Payments are non-refundable but may be transferable subject to management approval.', label_style))
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return buffer.getvalue()
