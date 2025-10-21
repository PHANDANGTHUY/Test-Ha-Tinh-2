import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai
import docx
import re
from io import BytesIO

# =================================================================================
# Cấu hình trang và các hàm tiện ích
# =================================================================================

st.set_page_config(
    page_title="Hệ thống Thẩm định Phương án Kinh doanh",
    page_icon="🏦",
    layout="wide"
)

def format_currency(value):
    """Định dạng số thành chuỗi tiền tệ với dấu chấm phân cách hàng nghìn."""
    if pd.isna(value):
        return ""
    return f"{int(value):,}".replace(",", ".")

def extract_text_from_docx(docx_file):
    """Trích xuất toàn bộ văn bản từ file .docx."""
    try:
        doc = docx.Document(docx_file)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return '\n'.join(full_text)
    except Exception as e:
        st.error(f"Lỗi khi đọc file .docx: {e}")
        return ""

def extract_info_from_text(text):
    """Trích xuất thông tin từ văn bản sử dụng regex."""
    extracted = {}
    
    # Trích xuất Họ và tên
    name_match = re.search(r'Họ và tên[:\s*]+([^\s]+(?:\s+[^\s]+)+?)[\s]*\.?\s*[Ss]inh', text, re.IGNORECASE)
    if name_match:
        extracted['full_name'] = name_match.group(1).strip().rstrip('*')
    
    # Trích xuất CCCD
    cccd_match = re.search(r'CCCD số[:\s]*([0-9]+)', text, re.IGNORECASE)
    if cccd_match:
        extracted['cccd'] = cccd_match.group(1).strip()
    
    # Trích xuất địa chỉ
    address_match = re.search(r'Nơi cư trú[:\s]*(.*?)(?:\n|Số điện thoại)', text, re.IGNORECASE | re.DOTALL)
    if address_match:
        addr = address_match.group(1).strip()
        addr = re.sub(r'\s+', ' ', addr)
        extracted['address'] = addr
    
    # Trích xuất SĐT
    phone_match = re.search(r'Số điện thoại[:\s]*([0-9]+)', text, re.IGNORECASE)
    if phone_match:
        extracted['phone'] = phone_match.group(1).strip()
    
    # Trích xuất Mục đích vay
    purpose_match = re.search(r'Mục đích vay[:\s]*(.*?)(?:\n|Thời gian|$)', text, re.IGNORECASE)
    if purpose_match:
        extracted['loan_purpose'] = purpose_match.group(1).strip()
    
    # Trích xuất Số tiền vay
    loan_match = re.search(r'Vốn vay Agribank[^\d]*([0-9.,]+)', text, re.IGNORECASE)
    if loan_match:
        loan_str = loan_match.group(1).replace('.', '').replace(',', '')
        try:
            extracted['loan_amount'] = float(loan_str)
        except:
            pass
    
    # Trích xuất Lãi suất
    rate_match = re.search(r'Lãi suất đề nghị[:\s]*([0-9.,]+)\s*%', text, re.IGNORECASE)
    if rate_match:
        try:
            extracted['interest_rate'] = float(rate_match.group(1).replace(',', '.'))
        except:
            pass
    
    # Trích xuất Thời gian vay
    term_match = re.search(r'Thời gian duy trì[^\d]*([0-9]+)\s*tháng', text, re.IGNORECASE)
    if term_match:
        try:
            extracted['loan_term'] = int(term_match.group(1))
        except:
            pass
    
    # Trích xuất Nhu cầu vốn lưu động
    capital_match = re.search(r'Nhu cầu vốn lưu động[^\d]*([0-9.,]+)', text, re.IGNORECASE)
    if capital_match:
        capital_str = capital_match.group(1).replace('.', '').replace(',', '')
        try:
            extracted['total_capital'] = float(capital_str)
        except:
            pass
    
    # Trích xuất Vốn đối ứng
    equity_match = re.search(r'Vốn đối ứng[^\d]*đồng\s*([0-9.,]+)', text, re.IGNORECASE)
    if equity_match:
        equity_str = equity_match.group(1).replace('.', '').replace(',', '')
        try:
            extracted['equity_capital'] = float(equity_str)
        except:
            pass
    
    # Trích xuất Tổng tài sản đảm bảo
    collateral_match = re.search(r'Tổng tài sản đảm bảo[:\s]*([0-9.,]+)', text, re.IGNORECASE)
    if collateral_match:
        collateral_str = collateral_match.group(1).replace('.', '').replace(',', '').replace('đồng', '')
        try:
            extracted['collateral_value'] = float(collateral_str)
        except:
            pass
    
    # Trích xuất mô tả tài sản
    collateral_desc_match = re.search(r'Tài sản bảo đảm:(.*?)(?=Tổng tài sản|III\.|$)', text, re.IGNORECASE | re.DOTALL)
    if collateral_desc_match:
        desc_text = collateral_desc_match.group(1).strip()
        first_asset = re.search(r'-\s*(Quyền sử dụng đất.*?)(?:\n-|\nTổng|Giá trị)', desc_text, re.DOTALL)
        if first_asset:
            desc = first_asset.group(1).strip()
            desc = re.sub(r'\s+', ' ', desc)
            extracted['collateral_desc'] = desc[:200] + "..." if len(desc) > 200 else desc
    
    return extracted

@st.cache_data
def calculate_repayment_schedule(loan_amount, annual_interest_rate, loan_term_months):
    """Tính toán bảng kế hoạch trả nợ chi tiết."""
    if not all([loan_amount > 0, annual_interest_rate > 0, loan_term_months > 0]):
        return pd.DataFrame()

    monthly_interest_rate = (annual_interest_rate / 100) / 12
    principal_per_month = loan_amount / loan_term_months
    
    schedule = []
    remaining_balance = loan_amount

    for i in range(1, loan_term_months + 1):
        interest_payment = remaining_balance * monthly_interest_rate
        total_payment = principal_per_month + interest_payment
        
        schedule.append({
            "Kỳ trả nợ": i,
            "Dư nợ đầu kỳ": remaining_balance,
            "Gốc trả trong kỳ": principal_per_month,
            "Lãi trả trong kỳ": interest_payment,
            "Tổng gốc và lãi": total_payment,
            "Dư nợ cuối kỳ": remaining_balance - principal_per_month
        })
        remaining_balance -= principal_per_month

    return pd.DataFrame(schedule)

def generate_excel_download(df):
    """Tạo file Excel trong bộ nhớ để tải về."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    processed_data = output.getvalue()
    return processed_data

def generate_report_text(ss):
    """Tạo nội dung text cho báo cáo thẩm định."""
    report_lines = [
        "BÁO CÁO THẨM ĐỊNH PHƯƠNG ÁN KINH DOANH",
        "="*40,
        "\n**PHẦN 1: THÔNG TIN KHÁCH HÀNG VÀ KHOẢN VAY**\n",
        f"- Họ và tên: {ss.get('full_name', 'Chưa có')}",
        f"- CCCD: {ss.get('cccd', 'Chưa có')}",
        f"- Địa chỉ: {ss.get('address', 'Chưa có')}",
        f"- SĐT: {ss.get('phone', 'Chưa có')}",
        "-"*20,
        f"- Mục đích vay: {ss.get('loan_purpose', 'Chưa có')}",
        f"- Tổng nhu cầu vốn: {format_currency(ss.get('total_capital', 0))} VND",
        f"- Vốn đối ứng: {format_currency(ss.get('equity_capital', 0))} VND",
        f"- Số tiền vay: {format_currency(ss.get('loan_amount', 0))} VND",
        f"- Lãi suất: {ss.get('interest_rate', 0)} %/năm",
        f"- Thời gian vay: {ss.get('loan_term', 0)} tháng",
        "-"*20,
        "**Tài sản đảm bảo:**",
        f"- Mô tả: {ss.get('collateral_desc', 'Chưa có')}",
        f"- Giá trị định giá: {format_currency(ss.get('collateral_value', 0))} VND",
        
        "\n**PHẦN 2: PHÂN TÍCH BỞI AI**\n",
        "**2.1. Phân tích từ file .docx của khách hàng:**",
        ss.get('ai_analysis_from_file', "Chưa thực hiện phân tích."),
        "\n**2.2. Phân tích từ các thông số đã tính toán trên ứng dụng:**",
        ss.get('ai_analysis_from_data', "Chưa thực hiện phân tích."),
    ]
    return "\n".join(report_lines)

# =================================================================================
# Khởi tạo Session State
# =================================================================================

if 'api_key' not in st.session_state:
    st.session_state.api_key = ''
if 'api_configured' not in st.session_state:
    st.session_state.api_configured = False
if 'docx_text' not in st.session_state:
    st.session_state.docx_text = ''

# Dữ liệu nhập liệu
if 'full_name' not in st.session_state:
    st.session_state.full_name = "Nguyễn Thị A"
if 'cccd' not in st.session_state:
    st.session_state.cccd = "012345678910"
if 'address' not in st.session_state:
    st.session_state.address = "Hà Nội, Việt Nam"
if 'phone' not in st.session_state:
    st.session_state.phone = "0987654321"
if 'loan_purpose' not in st.session_state:
    st.session_state.loan_purpose = "Bổ sung vốn lưu động kinh doanh vật liệu xây dựng"
if 'total_capital' not in st.session_state:
    st.session_state.total_capital = 7800000000.0
if 'equity_capital' not in st.session_state:
    st.session_state.equity_capital = 500000000.0
if 'loan_amount' not in st.session_state:
    st.session_state.loan_amount = 7300000000.0
if 'interest_rate' not in st.session_state:
    st.session_state.interest_rate = 5.0
if 'loan_term' not in st.session_state:
    st.session_state.loan_term = 12
if 'collateral_desc' not in st.session_state:
    st.session_state.collateral_desc = "Quyền sử dụng đất và tài sản gắn liền với đất tại..."
if 'collateral_value' not in st.session_state:
    st.session_state.collateral_value = 10000000000.0

# Kết quả phân tích
if 'repayment_df' not in st.session_state:
    st.session_state.repayment_df = pd.DataFrame()
if 'ai_analysis_from_file' not in st.session_state:
    st.session_state.ai_analysis_from_file = ""
if 'ai_analysis_from_data' not in st.session_state:
    st.session_state.ai_analysis_from_data = ""

# Chatbot
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# =================================================================================
# Giao diện chính
# =================================================================================

st.title("🏦 Hệ thống Thẩm định Phương án Kinh doanh")
st.caption("Ứng dụng nội bộ hỗ trợ chuyên viên tín dụng phân tích và thẩm định hồ sơ vay vốn")

# --- Thanh bên (Sidebar) ---
with st.sidebar:
    st.header("Cấu hình & Chức năng")
    
    api_key_input = st.text_input(
        "🔑 Gemini API Key", 
        type="password",
        value=st.session_state.api_key,
        help="Nhập API Key của bạn để kích hoạt các tính năng AI."
    )
    
    if api_key_input != st.session_state.api_key:
        st.session_state.api_key = api_key_input
        st.session_state.api_configured = False
    
    if st.session_state.api_key:
        if not st.session_state.api_configured:
            try:
                genai.configure(api_key=st.session_state.api_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                st.session_state.api_configured = True
                st.success("✅ API Key hợp lệ", icon="✅")
            except Exception as e:
                st.error(f"❌ API Key không hợp lệ: {str(e)}")
                st.session_state.api_configured = False
        else:
            st.success("✅ API Key đã được cấu hình", icon="✅")

    st.divider()

    st.header("Chức năng Xuất dữ liệu")
    export_option = st.selectbox(
        "Chọn loại báo cáo:",
        ("---", "Xuất Kế hoạch trả nợ (Excel)", "Xuất Báo cáo Thẩm định (Text)")
    )
    
    if st.button("Thực hiện Xuất", use_container_width=True):
        if export_option == "Xuất Kế hoạch trả nợ (Excel)":
            if not st.session_state.repayment_df.empty:
                excel_data = generate_excel_download(st.session_state.repayment_df)
                st.download_button(
                    label="📥 Tải về file Excel",
                    data=excel_data,
                    file_name="ke_hoach_tra_no.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            else:
                st.warning("Chưa có dữ liệu kế hoạch trả nợ để xuất.")
        elif export_option == "Xuất Báo cáo Thẩm định (Text)":
            report_content = generate_report_text(st.session_state)
            st.download_button(
                label="📥 Tải về Báo cáo",
                data=report_content.encode('utf-8'),
                file_name="bao_cao_tham_dinh.txt",
                mime="text/plain",
                use_container_width=True
            )
        else:
            st.info("Vui lòng chọn một chức năng để xuất dữ liệu.")

# --- Các Tab chính ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📄 Nhập liệu & Trích xuất thông tin",
    "📈 Phân tích Chỉ số & Dòng tiền",
    "📊 Biểu đồ Trực quan",
    "🤖 Phân tích bởi AI",
    "💬 Chatbot Hỗ trợ"
])

# --- Tab 1: Nhập liệu & Trích xuất thông tin ---
with tab1:
    st.header("Tải lên và Hiệu chỉnh Thông tin")
    uploaded_file = st.file_uploader(
        "Tải lên file Phương án kinh doanh của khách hàng (.docx)", 
        type=['docx']
    )

    if uploaded_file is not None:
        st.session_state.docx_text = extract_text_from_docx(uploaded_file)
        
        if st.session_state.docx_text:
            st.success("✅ Đã tải lên và trích xuất nội dung file thành công!")
            
            extracted_data = extract_info_from_text(st.session_state.docx_text)
            
            for key, value in extracted_data.items():
                st.session_state[key] = value
            
            if extracted_data:
                st.info(f"📝 Đã trích xuất được {len(extracted_data)} trường thông tin từ file")
                with st.expander("Xem thông tin đã trích xuất"):
                    for key, value in extracted_data.items():
                        st.write(f"**{key}**: {value}")

    st.subheader("Vui lòng kiểm tra và hiệu chỉnh lại các thông tin dưới đây:")
    
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown("##### 👤 Vùng 1 - Thông tin khách hàng")
            st.session_state.full_name = st.text_input("Họ và tên", st.session_state.full_name)
            st.session_state.cccd = st.text_input("CCCD", st.session_state.cccd)
            st.session_state.address = st.text_input("Địa chỉ", st.session_state.address)
            st.session_state.phone = st.text_input("Số điện thoại", st.session_state.phone)

    with col2:
        with st.container(border=True):
            st.markdown("##### 💰 Vùng 2 - Thông tin phương án vay")
            st.session_state.loan_purpose = st.text_input("Mục đích vay", st.session_state.loan_purpose)
            st.session_state.total_capital = st.number_input("Tổng nhu cầu vốn (VND)", value=st.session_state.total_capital, format="%f", step=10000000.0)
            st.session_state.equity_capital = st.number_input("Vốn đối ứng (VND)", value=st.session_state.equity_capital, format="%f", step=10000000.0)
            st.session_state.loan_amount = st.number_input("Số tiền vay (VND)", value=st.session_state.loan_amount, format="%f", step=10000000.0)
            st.session_state.interest_rate = st.number_input("Lãi suất (%/năm)", value=st.session_state.interest_rate, min_value=0.1, max_value=30.0, step=0.1)
            st.session_state.loan_term = st.number_input("Thời gian vay (tháng)", value=st.session_state.loan_term, min_value=1, step=1)

    with st.container(border=True):
        st.markdown("##### 🏠 Vùng 3 - Thông tin tài sản đảm bảo")
        st.session_state.collateral_desc = st.text_area("Mô tả tài sản", st.session_state.collateral_desc, height=100)
        st.session_state.collateral_value = st.number_input("Giá trị định giá (VND)", value=st.session_state.collateral_value, format="%f", step=10000000.0)

# --- Tab 2: Phân tích Chỉ số & Dòng tiền ---
with tab2:
    st.header("Các chỉ số tài chính và Kế hoạch trả nợ")

    if st.session_state.loan_amount > 0 and st.session_state.total_capital > 0:
        col1, col2, col3 = st.columns(3)
        
        loan_to_capital_ratio = (st.session_state.loan_amount / st.session_state.total_capital) * 100
        equity_ratio = (st.session_state.equity_capital / st.session_state.total_capital) * 100
        loan_to_collateral_ratio = (st.session_state.loan_amount / st.session_state.collateral_value) * 100 if st.session_state.collateral_value > 0 else 0

        col1.metric(
            label="Tỷ lệ Vay / Tổng nhu cầu vốn",
            value=f"{loan_to_capital_ratio:.2f} %"
        )
        col2.metric(
            label="Tỷ lệ Vốn đối ứng",
            value=f"{equity_ratio:.2f} %"
        )
        col3.metric(
            label="Tỷ lệ Vay / TSTB",
            value=f"{loan_to_collateral_ratio:.2f} %"
        )
        
        st.divider()

        st.subheader("Bảng kế hoạch trả nợ (dự kiến)")
        
        st.session_state.repayment_df = calculate_repayment_schedule(
            st.session_state.loan_amount,
            st.session_state.interest_rate,
            st.session_state.loan_term
        )
        
        if not st.session_state.repayment_df.empty:
            df_display = st.session_state.repayment_df.copy()
            for col_name in ["Dư nợ đầu kỳ", "Gốc trả trong kỳ", "Lãi trả trong kỳ", "Tổng gốc và lãi", "Dư nợ cuối kỳ"]:
                df_display[col_name] = df_display[col_name].apply(format_currency)
            
            st.dataframe(df_display, use_container_width=True, height=400)
        else:
            st.warning("Vui lòng nhập đầy đủ thông tin về khoản vay để xem kế hoạch trả nợ.")
    else:
        st.info("Vui lòng nhập đầy đủ thông tin ở tab 'Nhập liệu' để xem phân tích.")

# --- Tab 3: Biểu đồ Trực quan ---
with tab3:
    st.header("Trực quan hóa dữ liệu tài chính")

    if st.session_state.loan_amount > 0 and st.session_state.equity_capital > 0:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Cơ cấu nguồn vốn")
            labels = ['Vốn vay', 'Vốn đối ứng']
            values = [st.session_state.loan_amount, st.session_state.equity_capital]
            fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.3, textinfo='label+percent')])
            fig_pie.update_layout(
                title_text='Tỷ lệ Vốn vay và Vốn đối ứng',
                annotations=[dict(text='Vốn', x=0.5, y=0.5, font_size=20, showarrow=False)]
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            st.subheader("Biểu đồ dư nợ giảm dần")
            if not st.session_state.repayment_df.empty:
                df_repayment = st.session_state.repayment_df
                fig_line = go.Figure()
                fig_line.add_trace(go.Scatter(
                    x=df_repayment['Kỳ trả nợ'], 
                    y=df_repayment['Dư nợ cuối kỳ'], 
                    mode='lines+markers', 
                    name='Dư nợ cuối kỳ'
                ))
                fig_line.update_layout(
                    title='Dư nợ giảm dần qua các kỳ',
                    xaxis_title='Kỳ trả nợ (tháng)',
                    yaxis_title='Dư nợ (VND)'
                )
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.info("Chưa có dữ liệu kế hoạch trả nợ để vẽ biểu đồ.")
    else:
        st.info("Vui lòng nhập đầy đủ thông tin ở tab 'Nhập liệu' để xem biểu đồ.")

# --- Tab 4: Phân tích bởi AI ---
with tab4:
    st.header("Phân tích Chuyên sâu với Gemini AI")
    
    if not st.session_state.api_configured:
        st.warning("⚠️ Vui lòng nhập Gemini API Key hợp lệ ở thanh bên để sử dụng tính năng này.")
    else:
        if st.button("🔍 Bắt đầu Phân tích", type="primary", use_container_width=True):
            try:
                model = genai.GenerativeModel('gemini-1.5-flash')

                # Phân tích 1 - Dựa trên File gốc
                if st.session_state.docx_text:
                    with st.spinner("AI đang phân tích nội dung file .docx..."):
                        prompt1 = f"""
Bạn là một chuyên gia thẩm định tín dụng ngân hàng. Dựa vào nội dung của phương án kinh doanh dưới đây, hãy đưa ra một phân tích tổng quan.
Tập trung vào các điểm sau:
1. **Tổng quan về phương án:** Mô tả ngắn gọn mục tiêu và lĩnh vực kinh doanh.
2. **Điểm mạnh:** Những yếu tố tích cực, khả thi của phương án.
3. **Điểm yếu:** Những điểm còn thiếu sót, chưa rõ ràng.
4. **Rủi ro tiềm ẩn:** Các rủi ro có thể ảnh hưởng đến khả năng trả nợ của khách hàng.
5. **Đề xuất:** Gợi ý những câu hỏi hoặc thông tin cần làm rõ thêm với khách hàng.

Nội dung phương án kinh doanh:
---
{st.session_state.docx_text[:8000]}
---
"""
                        response1 = model.generate_content(prompt1)
                        st.session_state.ai_analysis_from_file = response1.text
                else:
                    st.session_state.ai_analysis_from_file = "Không có file .docx nào được tải lên để phân tích."

                # Phân tích 2 - Dựa trên Dữ liệu đã hiệu chỉnh
                with st.spinner("AI đang phân tích các chỉ số tài chính..."):
                    loan_to_capital_ratio = 0
                    if st.session_state.total_capital > 0:
                        loan_to_capital_ratio = (st.session_state.loan_amount / st.session_state.total_capital) * 100
                    
                    loan_to_collateral_ratio = 0
                    if st.session_state.collateral_value > 0:
                        loan_to_collateral_ratio = (st.session_state.loan_amount / st.session_state.collateral_value) * 100
                    
                    data_summary = f"""
- Mục đích vay: {st.session_state.loan_purpose}
- Tổng nhu cầu vốn: {format_currency(st.session_state.total_capital)} VND
- Vốn đối ứng: {format_currency(st.session_state.equity_capital)} VND
- Số tiền vay: {format_currency(st.session_state.loan_amount)} VND
- Lãi suất: {st.session_state.interest_rate} %/năm
- Thời gian vay: {st.session_state.loan_term} tháng
- Tổng giá trị TSBĐ: {format_currency(st.session_state.collateral_value)} VND
- Tỷ lệ Vay/Tổng nhu cầu vốn: {loan_to_capital_ratio:.2f} %
- Tỷ lệ Vay/TSBĐ: {loan_to_collateral_ratio:.2f} %
"""
                    prompt2 = f"""
Bạn là một chuyên gia thẩm định tín dụng ngân hàng. Dựa vào các thông số tài chính của một khoản vay dưới đây, hãy đưa ra nhận định về tính khả thi.
Phân tích các khía cạnh sau:
1. **Tính hợp lý của các chỉ số:** Đánh giá các tỷ lệ Vay/Tổng vốn, Vay/TSBĐ. Các chỉ số này có an toàn cho ngân hàng không?
2. **Khả năng trả nợ:** Dựa trên số tiền vay và thời hạn, nhận xét về áp lực trả nợ hàng tháng lên khách hàng.
3. **Rủi ro tài chính:** Dựa trên các con số này, có rủi ro nào đáng chú ý không (ví dụ: đòn bẩy tài chính quá cao, TSBĐ chưa đủ...)?
4. **Kết luận sơ bộ:** Đưa ra kết luận ban đầu về mức độ rủi ro của khoản vay này.

Dữ liệu tài chính:
---
{data_summary}
---
"""
                    response2 = model.generate_content(prompt2)
                    st.session_state.ai_analysis_from_data = response2.text

                st.success("✅ Hoàn tất phân tích!")

            except Exception as e:
                st.error(f"Đã xảy ra lỗi khi gọi Gemini API: {e}")
    
    if st.session_state.ai_analysis_from_file or st.session_state.ai_analysis_from_data:
        with st.container(border=True):
            st.markdown("##### 📝 **Phân tích 1: Dựa trên File gốc**")
            st.caption("_Nguồn dữ liệu: Phân tích từ file .docx của khách hàng._")
            st.markdown(st.session_state.ai_analysis_from_file)
        
        st.write("")

        with st.container(border=True):
            st.markdown("##### 💹 **Phân tích 2: Dựa trên Dữ liệu đã hiệu chỉnh**")
            st.caption("_Nguồn dữ liệu: Phân tích từ các thông số và chỉ số đã tính toán trên ứng dụng._")
            st.markdown(st.session_state.ai_analysis_from_data)

# --- Tab 5: Chatbot Hỗ trợ ---
with tab5:
    st.header("Chatbot Hỗ trợ nghiệp vụ")

    if not st.session_state.api_configured:
        st.warning("⚠️ Vui lòng nhập Gemini API Key hợp lệ ở thanh bên để sử dụng tính năng này.")
    else:
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')

            # Hiển thị lịch sử chat
            for message in st.session_state.chat_history:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # Nhận input từ người dùng
            if prompt := st.chat_input("Bạn cần hỗ trợ gì về nghiệp vụ tín dụng?"):
                st.session_state.chat_history.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)
                
                with st.chat_message("assistant"):
                    with st.spinner("AI đang suy nghĩ..."):
                        context_history = []
                        for msg in st.session_state.chat_history:
                            context_history.append(f"{msg['role']}: {msg['content']}")
                        full_prompt = "\n".join(context_history)

                        response = model.generate_content(full_prompt)
                        response_text = response.text
                        st.markdown(response_text)
                
                st.session_state.chat_history.append({"role": "assistant", "content": response_text})

            if st.session_state.chat_history:
                if st.button("🗑️ Xóa lịch sử trò chuyện"):
                    st.session_state.chat_history = []
                    st.rerun()

        except Exception as e:
            st.error(f"Đã xảy ra lỗi với Chatbot: {e}")
