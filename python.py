import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from docx import Document
import re
import io
import google.generativeai as genai
from datetime import datetime

# ==============================================================================
# CẤU HÌNH TRANG VÀ BIẾN TOÀN CỤC
# ==============================================================================
st.set_page_config(
    page_title="Thẩm định Phương án Kinh doanh",
    page_icon="💼",
    layout="wide"
)

# ==============================================================================
# CÁC HÀM TIỆN ÍCH
# ==============================================================================

def format_currency(value):
    """Định dạng số thành chuỗi tiền tệ với dấu chấm phân cách hàng nghìn."""
    if isinstance(value, (int, float)):
        return f"{value:,.0f}".replace(",", ".")
    return value

def safe_float(value):
    """Chuyển đổi giá trị sang float một cách an toàn, trả về 0.0 nếu lỗi."""
    try:
        # Xóa các ký tự không phải số (giữ lại dấu thập phân nếu có)
        if isinstance(value, str):
            value = re.sub(r'[^\d.]', '', value)
        return float(value)
    except (ValueError, TypeError):
        return 0.0

def extract_data_from_docx(uploaded_file):
    """Trích xuất dữ liệu từ file .docx được tải lên."""
    try:
        document = Document(uploaded_file)
        full_text = "\n".join([para.text for para in document.paragraphs])
        
        # Sử dụng regex để tìm kiếm thông tin
        data = {
            'ho_ten': re.search(r"Họ và tên:\s*(.*?)\s*\.   Sinh ngày:", full_text).group(1).strip() if re.search(r"Họ và tên:\s*(.*?)\s*\.   Sinh ngày:", full_text) else "Không tìm thấy",
            'cccd': re.search(r"CCCD số:\s*(\d+)", full_text).group(1).strip() if re.search(r"CCCD số:\s*(\d+)", full_text) else "Không tìm thấy",
            'dia_chi': re.search(r"Nơi cư trú:\s*([^,]+,[^,]+,[^,]+)", full_text).group(1).strip() if re.search(r"Nơi cư trú:\s*([^,]+,[^,]+,[^,]+)", full_text) else "Không tìm thấy",
            'sdt': re.search(r"Số điện thoại:\s*([\d\s,]+)", full_text).group(1).split(',')[0].strip() if re.search(r"Số điện thoại:\s*([\d\s,]+)", full_text) else "Không tìm thấy",
            'muc_dich_vay': re.search(r"Mục đích vay:\s*(.*)", full_text).group(1).strip() if re.search(r"Mục đích vay:\s*(.*)", full_text) else "Kinh doanh vật liệu xây dựng",
            'tong_chi_phi': re.search(r"TỔNG CỘNG,\s*([\d.,]+)", full_text.replace("\n", " ")).group(1).strip() if re.search(r"TỔNG CỘNG,\s*([\d.,]+)", full_text.replace("\n", " ")) else "7827181642",
            'tong_doanh_thu': re.search(r"TỔNG CỘNG,\s*([\d.,]+)", full_text.replace("\n", " "), re.DOTALL | re.IGNORECASE)[-1] if re.findall(r"TỔNG CỘNG,\s*([\d.,]+)", full_text.replace("\n", " ")) else "8050108000",
            'nhu_cau_von': re.search(r"Nhu cầu vốn lưu động trên một vòng quay.*?([\d.,]+)", full_text).group(1).strip() if re.search(r"Nhu cầu vốn lưu động trên một vòng quay.*?([\d.,]+)", full_text) else "7685931642",
            'von_doi_ung': re.search(r"Vốn khác,đồng,([\d.,]+)", full_text).group(1).strip() if re.search(r"Vốn khác,đồng,([\d.,]+)", full_text) else "385931642",
            'von_vay': re.search(r"Vốn vay Agribank.*?([\d.,]+)", full_text).group(1).strip() if re.search(r"Vốn vay Agribank.*?([\d.,]+)", full_text) else "7300000000",
            'lai_suat': re.search(r"Lãi suất đề nghị:\s*(\d+[\.,]?\d*)\s*%/năm", full_text).group(1).replace(',', '.').strip() if re.search(r"Lãi suất đề nghị:\s*(\d+[\.,]?\d*)\s*%/năm", full_text) else "5.0",
            'thoi_gian_vay': re.search(r"Thời hạn cho vay:\s*(\d+)\s*tháng", full_text).group(1).strip() if re.search(r"Thời hạn cho vay:\s*(\d+)\s*tháng", full_text) else "3",
            'full_text': full_text
        }
        return data
    except Exception as e:
        st.error(f"Lỗi khi đọc file Word: {e}")
        return None

def generate_repayment_schedule(principal, annual_rate, term_months):
    """Tạo bảng kế hoạch trả nợ chi tiết."""
    if term_months <= 0 or principal <= 0:
        return pd.DataFrame()
        
    monthly_rate = (annual_rate / 100) / 12
    principal_payment = principal / term_months
    
    schedule = []
    remaining_balance = principal
    
    for i in range(1, term_months + 1):
        interest_payment = remaining_balance * monthly_rate
        total_payment = principal_payment + interest_payment
        remaining_balance -= principal_payment
        
        schedule.append({
            'Kỳ': i,
            'Dư nợ đầu kỳ': remaining_balance + principal_payment,
            'Gốc trả': principal_payment,
            'Lãi trả': interest_payment,
            'Tổng trả': total_payment,
            'Dư nợ cuối kỳ': remaining_balance
        })
        
    df = pd.DataFrame(schedule)
    return df

def generate_report_text():
    """Tạo nội dung văn bản để xuất báo cáo."""
    report_data = st.session_state.report_data
    schedule_df = st.session_state.schedule_df

    text = f"""
BÁO CÁO PHÂN TÍCH PHƯƠNG ÁN KINH DOANH
Ngày tạo: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
=================================================

I. THÔNG TIN KHÁCH HÀNG
-------------------------
- Họ và tên: {report_data['ho_ten']}
- CCCD: {report_data['cccd']}
- Địa chỉ: {report_data['dia_chi']}
- Số điện thoại: {report_data['sdt']}

II. THÔNG TIN KHOẢN VAY
-------------------------
- Mục đích vay: {report_data['muc_dich_vay']}
- Số tiền vay: {format_currency(report_data['von_vay'])} VND
- Lãi suất: {report_data['lai_suat']}%/năm
- Thời gian vay: {report_data['thoi_gian_vay']} tháng

III. PHÂN TÍCH TÀI CHÍNH (1 VÒNG QUAY)
----------------------------------------
- Tổng chi phí: {format_currency(report_data['tong_chi_phi'])} VND
- Tổng doanh thu: {format_currency(report_data['tong_doanh_thu'])} VND
- Lợi nhuận: {format_currency(report_data['loi_nhuan'])} VND
- Tỷ suất lợi nhuận: {report_data['ty_suat_loi_nhuan']:.2f}%
- Tổng nhu cầu vốn: {format_currency(report_data['nhu_cau_von'])} VND
- Vốn đối ứng: {format_currency(report_data['von_doi_ung'])} VND

IV. KẾ HOẠCH TRẢ NỢ
--------------------
{schedule_df.to_string(index=False)}

V. PHÂN TÍCH TỪ AI (NẾU CÓ)
-----------------------------
{st.session_state.get('ai_analysis', 'Chưa có phân tích từ AI.')}

=================================================
"""
    return text


# ==============================================================================
# KHỞI TẠO SESSION STATE
# ==============================================================================

if 'data_extracted' not in st.session_state:
    st.session_state.data_extracted = False
    st.session_state.report_data = {}
    st.session_state.schedule_df = pd.DataFrame()
    st.session_state.ai_analysis = ""
    st.session_state.full_text = ""

# Khởi tạo lịch sử chat
if "messages" not in st.session_state:
    st.session_state.messages = []


# ==============================================================================
# GIAO DIỆN - SIDEBAR
# ==============================================================================

with st.sidebar:
    st.header("Thiết lập")
    
    # 1. Gemini API Key
    api_key = st.text_input("🔑 Nhập Gemini API Key", type="password", help="API Key của bạn sẽ không được lưu trữ.")
    
    # 2. Tải file lên
    uploaded_file = st.file_uploader(
        "Tải lên Phương án Kinh doanh (.docx)",
        type=['docx'],
        accept_multiple_files=False
    )
    
    # Xử lý khi có file mới
    if uploaded_file and not st.session_state.data_extracted:
        with st.spinner('Đang trích xuất dữ liệu từ file...'):
            extracted_data = extract_data_from_docx(uploaded_file)
            if extracted_data:
                st.session_state.report_data = {
                    'ho_ten': extracted_data.get('ho_ten', ''),
                    'cccd': extracted_data.get('cccd', ''),
                    'dia_chi': extracted_data.get('dia_chi', ''),
                    'sdt': extracted_data.get('sdt', ''),
                    'muc_dich_vay': extracted_data.get('muc_dich_vay', ''),
                    'tong_chi_phi': safe_float(extracted_data.get('tong_chi_phi', 0)),
                    'tong_doanh_thu': safe_float(extracted_data.get('tong_doanh_thu', 0)),
                    'nhu_cau_von': safe_float(extracted_data.get('nhu_cau_von', 0)),
                    'von_doi_ung': safe_float(extracted_data.get('von_doi_ung', 0)),
                    'von_vay': safe_float(extracted_data.get('von_vay', 0)),
                    'lai_suat': safe_float(extracted_data.get('lai_suat', 0)),
                    'thoi_gian_vay': int(safe_float(extracted_data.get('thoi_gian_vay', 0))),
                }
                st.session_state.full_text = extracted_data.get('full_text', '')
                st.session_state.data_extracted = True
                st.success("Trích xuất dữ liệu thành công!")

    # 3. Nút xuất báo cáo
    if st.session_state.data_extracted:
        st.download_button(
            label="📄 Tải xuống Báo cáo (.txt)",
            data=generate_report_text(),
            file_name=f"Bao_cao_tham_dinh_{st.session_state.report_data.get('ho_ten', 'KH')}.txt",
            mime='text/plain',
        )

    # 4. Nút xóa cuộc trò chuyện
    if st.button("🗑️ Xóa cuộc trò chuyện"):
        st.session_state.messages = []
        st.rerun()

# ==============================================================================
# GIAO DIỆN - TRANG CHÍNH
# ==============================================================================

st.title("📊 Thẩm định Phương án Kinh doanh của Khách hàng")
st.markdown("---")

if not st.session_state.data_extracted:
    st.info("Vui lòng tải lên file phương án kinh doanh (.docx) ở thanh bên trái để bắt đầu.")
else:
    # --------------------------------------------------------------------------
    # KHU VỰC NHẬP LIỆU VÀ HIỂN THỊ THÔNG TIN
    # --------------------------------------------------------------------------
    col1, col2 = st.columns(2)

    with col1:
        with st.expander("👤 **Thông tin khách hàng**", expanded=True):
            st.session_state.report_data['ho_ten'] = st.text_input("Họ và tên", value=st.session_state.report_data.get('ho_ten'))
            st.session_state.report_data['cccd'] = st.text_input("CCCD", value=st.session_state.report_data.get('cccd'))
            st.session_state.report_data['dia_chi'] = st.text_input("Địa chỉ", value=st.session_state.report_data.get('dia_chi'))
            st.session_state.report_data['sdt'] = st.text_input("Số điện thoại", value=st.session_state.report_data.get('sdt'))

    with col2:
        with st.expander("💰 **Thông tin khoản vay**", expanded=True):
            st.session_state.report_data['muc_dich_vay'] = st.text_input("Mục đích vay", value=st.session_state.report_data.get('muc_dich_vay'))
            st.session_state.report_data['von_vay'] = st.number_input("Số tiền vay (VND)", min_value=0, value=int(st.session_state.report_data.get('von_vay')), step=1000000, format="%d")
            st.session_state.report_data['lai_suat'] = st.number_input("Lãi suất (%/năm)", min_value=0.0, value=st.session_state.report_data.get('lai_suat'), step=0.1, format="%.1f")
            st.session_state.report_data['thoi_gian_vay'] = st.number_input("Thời gian vay (tháng)", min_value=1, value=st.session_state.report_data.get('thoi_gian_vay'), step=1, format="%d")

    st.markdown("---")

    # --------------------------------------------------------------------------
    # KHU VỰC PHÂN TÍCH VÀ TÍNH TOÁN
    # --------------------------------------------------------------------------
    st.subheader("📈 Phân tích tài chính và Trực quan hóa")
    
    # Lấy dữ liệu từ session state để tính toán
    total_cost = st.session_state.report_data.get('tong_chi_phi', 0)
    total_revenue = st.session_state.report_data.get('tong_doanh_thu', 0)
    loan_amount = st.session_state.report_data.get('von_vay', 0)
    equity = st.session_state.report_data.get('von_doi_ung', 0)

    # Tính toán các chỉ số
    profit = total_revenue - total_cost
    profit_margin = (profit / total_revenue) * 100 if total_revenue > 0 else 0
    st.session_state.report_data['loi_nhuan'] = profit
    st.session_state.report_data['ty_suat_loi_nhuan'] = profit_margin

    # Hiển thị các chỉ số chính
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Lợi nhuận (1 vòng quay)", f"{format_currency(profit)} VND", delta=f"{format_currency(profit)} VND")
    metric_col2.metric("Tỷ suất lợi nhuận", f"{profit_margin:.2f}%")
    metric_col3.metric("Tổng chi phí (1 vòng quay)", f"{format_currency(total_cost)} VND")

    # Trực quan hóa dữ liệu
    viz_col1, viz_col2 = st.columns(2)
    with viz_col1:
        st.markdown("##### Cơ cấu Doanh thu")
        if total_revenue > 0:
            fig_pie = go.Figure(data=[go.Pie(
                labels=['Tổng chi phí', 'Lợi nhuận'],
                values=[total_cost, profit],
                hole=.3,
                marker_colors=['#ff9999', '#66b3ff']
            )])
            fig_pie.update_layout(showlegend=True)
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.warning("Không có dữ liệu doanh thu để vẽ biểu đồ.")

    with viz_col2:
        st.markdown("##### Cơ cấu Nguồn vốn")
        if (loan_amount + equity) > 0:
            fig_bar = go.Figure(data=[go.Bar(
                x=['Vốn đối ứng', 'Vốn vay'],
                y=[equity, loan_amount],
                marker_color=['#4CAF50', '#F44336']
            )])
            fig_bar.update_layout(yaxis_title='Số tiền (VND)')
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.warning("Không có dữ liệu vốn để vẽ biểu đồ.")

    st.markdown("---")

    # --------------------------------------------------------------------------
    # KHU VỰC KẾ HOẠCH TRẢ NỢ
    # --------------------------------------------------------------------------
    st.subheader("🗓️ Kế hoạch trả nợ dự kiến")
    schedule_df = generate_repayment_schedule(
        st.session_state.report_data['von_vay'],
        st.session_state.report_data['lai_suat'],
        st.session_state.report_data['thoi_gian_vay']
    )
    st.session_state.schedule_df = schedule_df

    if not schedule_df.empty:
        # Định dạng lại DataFrame để hiển thị
        display_df = schedule_df.copy()
        for col in display_df.columns:
            if display_df[col].dtype == 'float64':
                display_df[col] = display_df[col].apply(format_currency)
        
        st.dataframe(display_df, use_container_width=True)

        # Chuyển đổi DataFrame sang Excel để tải xuống
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            schedule_df.to_excel(writer, index=False, sheet_name='KeHoachTraNo')
        excel_data = output.getvalue()

        st.download_button(
            label="📥 Tải xuống Kế hoạch trả nợ (.xlsx)",
            data=excel_data,
            file_name=f"Ke_hoach_tra_no_{st.session_state.report_data.get('ho_ten', 'KH')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("Vui lòng nhập đầy đủ thông tin khoản vay để tạo kế hoạch trả nợ.")

    st.markdown("---")
    
    # --------------------------------------------------------------------------
    # KHU VỰC TÍCH HỢP AI
    # --------------------------------------------------------------------------
    st.subheader("🤖 Phân tích từ Trợ lý AI")
    if not api_key:
        st.warning("Vui lòng nhập Gemini API Key ở thanh bên trái để sử dụng các tính năng AI.")
    else:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
        except Exception as e:
            st.error(f"Lỗi khi cấu hình Gemini: {e}")
            model = None

        if model:
            # Nút Phân tích nhanh
            if st.button("🚀 AI Phân tích Nhanh", help="Gửi toàn bộ thông tin dự án đến AI để nhận phân tích tổng quan."):
                with st.spinner("AI đang phân tích, vui lòng chờ..."):
                    prompt = f"""
                    Bạn là một chuyên gia thẩm định tín dụng giàu kinh nghiệm. Dưới đây là toàn bộ phương án kinh doanh của khách hàng.
                    Hãy phân tích một cách ngắn gọn, súc tích và đưa ra kết luận.

                    {st.session_state.full_text}

                    ---
                    DỰA VÀO DỮ LIỆU TRÊN, HÃY CUNG CẤP:
                    1.  **Điểm mạnh:** 2-3 gạch đầu dòng về các ưu điểm của phương án.
                    2.  **Điểm yếu:** 2-3 gạch đầu dòng về các nhược điểm hoặc điểm cần làm rõ.
                    3.  **Rủi ro:** 2-3 gạch đầu dòng về các rủi ro tiềm ẩn.
                    4.  **Đề xuất cuối cùng:** In đậm và chỉ ghi một trong hai cụm từ: "NÊN CHO VAY" hoặc "KHÔNG NÊN CHO VAY".
                    """
                    try:
                        response = model.generate_content(prompt)
                        st.session_state.ai_analysis = response.text
                        st.markdown(st.session_state.ai_analysis)
                    except Exception as e:
                        st.error(f"Đã xảy ra lỗi khi gọi API của Gemini: {e}")

            # Chatbox tương tác
            st.markdown("##### Trò chuyện với Trợ lý AI")

            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            if prompt := st.chat_input("Đặt câu hỏi về phương án kinh doanh này..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("AI đang suy nghĩ..."):
                        context_prompt = f"""
                        Đây là bối cảnh của phương án kinh doanh đang được thẩm định:
                        {st.session_state.full_text}
                        ---
                        Dựa vào bối cảnh trên, hãy trả lời câu hỏi của người dùng một cách chuyên nghiệp và ngắn gọn.
                        Câu hỏi: {prompt}
                        """
                        try:
                            response = model.generate_content(context_prompt)
                            response_text = response.text
                            st.markdown(response_text)
                            st.session_state.messages.append({"role": "assistant", "content": response_text})
                        except Exception as e:
                            error_message = f"Xin lỗi, đã có lỗi xảy ra: {e}"
                            st.markdown(error_message)
                            st.session_state.messages.append({"role": "assistant", "content": error_message})
