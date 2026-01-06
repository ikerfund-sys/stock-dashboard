import base64
import io
import time
import urllib.parse
import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import mimetypes
import traceback

# 1. 修正 MIME Types
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

# --- CSS 定義 ---
nebula_css_string = '''
    :root {
        --bg-color: #050510;
        --card-bg: rgba(20, 20, 35, 0.7);
        --neon-blue: #00f2ff;
        --neon-purple: #bc13fe;
        --text-main: #e0e0e0;
    }
    body {
        background-color: var(--bg-color) !important;
        background-image: radial-gradient(circle at 50% 10%, #1a1a2e 0%, var(--bg-color) 70%);
        color: var(--text-main);
        font-family: 'Segoe UI', Roboto, sans-serif;
    }
    .nebula-title {
        text-shadow: 0 0 10px var(--neon-blue), 0 0 20px var(--neon-purple);
        font-weight: 700;
        letter-spacing: 2px;
    }
    .card {
        background-color: var(--card-bg) !important;
        border: 1px solid rgba(0, 242, 255, 0.2);
        box-shadow: 0 0 15px rgba(0, 0, 0, 0.5);
        backdrop-filter: blur(10px);
    }
    .upload-box {
        border: 2px dashed var(--neon-blue) !important;
        background: rgba(0, 242, 255, 0.05);
        transition: all 0.3s ease;
        color: var(--neon-blue);
        cursor: pointer;
    }
    .upload-box:hover {
        background: rgba(0, 242, 255, 0.1);
        box-shadow: 0 0 20px rgba(0, 242, 255, 0.3);
        transform: scale(1.01);
    }
    .progress-container {
        display: none;
        margin-top: 20px;
        text-align: center;
    }
    .progress-bar-nebula {
        width: 0%;
        height: 4px;
        background: linear-gradient(90deg, var(--neon-blue), var(--neon-purple));
        box-shadow: 0 0 10px var(--neon-blue);
        border-radius: 2px;
        transition: width 0.2s ease-out;
    }
    .loading-text {
        color: var(--neon-blue);
        font-family: monospace;
        margin-bottom: 5px;
    }
    /* 表格樣式 */
    .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner th {
        background-color: #1f1f2e !important;
        color: var(--neon-blue) !important;
        border-bottom: 1px solid var(--neon-blue) !important;
        font-weight: bold;
    }
    .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td {
        background-color: var(--card-bg) !important;
        color: #fff !important;
        border: none !important;
    }
    .nav-tabs .nav-link.active {
        background-color: var(--card-bg) !important;
        border-color: var(--neon-blue) !important;
        color: var(--neon-blue) !important;
    }
    .nav-tabs .nav-link {
        color: #888 !important;
    }
    /* 結果顯示區預設為隱藏 */
    #content-wrapper {
        display: none;
        opacity: 0;
        transition: opacity 0.8s ease-in;
    }
'''

# --- CSS 轉碼 ---
encoded_css = urllib.parse.quote(nebula_css_string)
css_data_uri = f"data:text/css;charset=utf-8,{encoded_css}"

# --- 初始化 Dash ---
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.DARKLY, css_data_uri]
)
app.title = "對帳單解析"
server = app.server

# --- 資料處理輔助函式 ---

def clean_currency(x):
    """清理金額/數量欄位：移除逗號、空白，並轉為浮點數"""
    if pd.isna(x):
        return 0.0
    s = str(x).replace(',', '').replace(' ', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

def clean_date(x):
    """統一日期格式：轉為 YYYYMMDD 字串"""
    if pd.isna(x):
        return ""
    s = str(x).strip()
    # 嘗試標準日期解析
    try:
        dt = pd.to_datetime(s, errors='coerce')
        if pd.notna(dt):
            return dt.strftime('%Y%m%d')
    except:
        pass
    # 若無法解析，則單純移除分隔符號
    return s.replace('/', '').replace('-', '')

def normalize_dataframe(df):
    """
    核心邏輯：將不同券商的損益表統一為「已實現.xlsx」的標準格式。
    """
    # 移除完全空白的列
    df = df.dropna(how='all')
    if df.empty:
        return df

    # 格式自動偵測
    # 檢查第 2 欄 (Index 1) 的內容
    # 已實現.xlsx: B欄是「類別」(文字，如融資、現股)
    # 證券_歷史已實損益.xlsx: B欄是「成交日期」(日期格式)
    
    first_row_b_val = str(df.iloc[0, 1]).strip()
    
    is_history_format = False
    # 簡易日期特徵判斷 (包含斜線、破折號或純8碼數字)
    if '/' in first_row_b_val or '-' in first_row_b_val or (first_row_b_val.isdigit() and len(first_row_b_val) == 8):
        is_history_format = True
    
    # 建立標準資料字典
    new_data = {}
    
    if is_history_format:
        # === 處理格式：證券_歷史已實損益.xlsx ===
        # 對應邏輯：
        # A(0):商品, B(1):日期, C(2):類別(需截斷), D(3):數量, E(4):價格(推斷), F(5):賣出, G(6):買進, H(7):損益, I(8):報酬
        
        new_data['商品'] = df.iloc[:, 0].astype(str).str.strip()
        new_data['類別'] = df.iloc[:, 2].astype(str).str.strip().str[:2] # 截取前2字
        new_data['成交日期'] = df.iloc[:, 1]
        new_data['成交數量'] = df.iloc[:, 3]
        new_data['成交價格'] = df.iloc[:, 4] 
        new_data['買進金額'] = df.iloc[:, 6] # 注意：此格式 G 欄是買進
        new_data['賣出金額'] = df.iloc[:, 5] # 注意：此格式 F 欄是賣出
        new_data['損益試算'] = df.iloc[:, 7]
        new_data['報酬率'] = df.iloc[:, 8]
        
    else:
        # === 處理格式：已實現.xlsx (基準) ===
        # 對應邏輯：
        # A(0):商品, B(1):類別, C(2):日期, D(3):數量, E(4):價格, F(5):買進, G(6):賣出
        
        # 使用 iloc 確保位置正確，忽略 header 名稱微小差異
        new_data['商品'] = df.iloc[:, 0].astype(str).str.strip()
        new_data['類別'] = df.iloc[:, 1].astype(str).str.strip()
        new_data['成交日期'] = df.iloc[:, 2]
        new_data['成交數量'] = df.iloc[:, 3]
        new_data['成交價格'] = df.iloc[:, 4]
        new_data['買進金額'] = df.iloc[:, 5]
        new_data['賣出金額'] = df.iloc[:, 6]
        new_data['損益試算'] = df.iloc[:, 7]
        new_data['報酬率'] = df.iloc[:, 8]
        
    df_out = pd.DataFrame(new_data)
    
    # 統一清洗數據
    df_out['成交日期'] = df_out['成交日期'].apply(clean_date)
    
    numeric_cols = ['成交數量', '成交價格', '買進金額', '賣出金額', '損益試算', '報酬率']
    for col in numeric_cols:
        df_out[col] = df_out[col].apply(clean_currency)
        
    return df_out

def parse_contents(contents, filename):
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    try:
        df = None
        if 'csv' in filename.lower():
            try:
                # 優先嘗試 UTF-8
                df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
            except:
                # 若失敗則嘗試 Big5 (常見於舊版 Excel 匯出的 CSV)
                df = pd.read_csv(io.StringIO(decoded.decode('big5')))
        elif 'xls' in filename.lower():
            df = pd.read_excel(io.BytesIO(decoded))
        else:
            return None, "不支援的檔案格式"
        
        # 模擬運算延遲
        time.sleep(1.0)
        
        # --- 呼叫標準化函式 ---
        if df is not None:
            df = normalize_dataframe(df)
            
            # --- 額外計算 ---
            if '買進金額' in df.columns and '賣出金額' in df.columns:
                # 避免分母為0
                df['單筆報酬率'] = df.apply(lambda row: (row['賣出金額'] / row['買進金額'] - 1) if row['買進金額'] != 0 else 0, axis=1)
                
            # 確保日期欄位為 datetime 物件以便後續 resample 使用
            df['成交日期'] = pd.to_datetime(df['成交日期'], format='%Y%m%d', errors='coerce')
            
            return df, None
        return None, "讀取失敗"

    except Exception as e:
        return None, str(e)

def format_currency(value):
    return f"{int(value):,}"

def format_percent(value):
    return f"{value:.2%}"

def generate_table(dataframe, display_cols=None):
    if display_cols:
        df_display = dataframe[display_cols].copy()
    else:
        df_display = dataframe.copy()
    return dash_table.DataTable(
        data=df_display.to_dict('records'),
        columns=[{'name': i, 'id': i} for i in df_display.columns],
        style_table={'overflowX': 'auto'},
        page_size=10
    )

def plot_period_bar(df_resampled, title):
    colors = ['#ff2a6d' if x > 0 else '#00f2ff' for x in df_resampled['損益試算']]
    fig = go.Figure(data=[
        go.Bar(
            x=df_resampled.index,
            y=df_resampled['損益試算'],
            marker_color=colors,
            marker_line_width=0
        )
    ])
    fig.update_layout(
        title=dict(text=title, font=dict(color='#e0e0e0', size=18)),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#a0a0a0'),
        yaxis=dict(gridcolor='rgba(255,255,255,0.1)', zerolinecolor='rgba(255,255,255,0.2)'),
        margin=dict(l=40, r=40, t=40, b=40)
    )
    return fig

# --- Layout ---

app.layout = dbc.Container([
    dbc.Row([dbc.Col(html.H2("對帳單解析", className="text-center mt-5 mb-4 nebula-title"), width=12)]),

    dbc.Row([
        dbc.Col([
            dcc.Upload(
                id='upload-data',
                children=html.Div([
                    '拖拉檔案至此 或 ', 
                    html.Span('點擊上傳', style={'textDecoration': 'underline', 'fontWeight': 'bold'})
                ]),
                style={
                    'width': '100%', 'height': '80px', 'lineHeight': '80px',
                    'borderWidth': '1px', 'borderStyle': 'dashed',
                    'borderRadius': '10px', 'textAlign': 'center', 'margin': '10px'
                },
                className='upload-box',
                multiple=False
            ),
            # 進度條 (初始為隱藏)
            html.Div([
                html.Div(id='loading-text-display', className='loading-text', children='準備中...'),
                html.Div(html.Div(id='progress-bar-inner', className='progress-bar-nebula'), 
                         style={'width': '0%', 'backgroundColor': '#1a1a2e', 'borderRadius': '2px'})
            ], id='progress-section', className='progress-container'),
            
        ], width={"size": 8, "offset": 2})
    ]),

    html.Hr(style={'borderColor': 'rgba(255,255,255,0.1)'}),

    # 信號儲存器
    dcc.Store(id='signal-store'),
    
    # 包裹內容的容器
    html.Div(id='content-wrapper', children=[
        html.Div(id='output-content')
    ])

], fluid=True, style={'minHeight': '100vh'})


# --- Callbacks ---

# 1. Server-side Logic (Python)
@app.callback(
    [Output('output-content', 'children'),
     Output('signal-store', 'data')],
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename')],
    prevent_initial_call=True
)
def update_output(contents, filename):
    if contents is None:
        return html.Div(), dash.no_update
    
    try:
        # 使用新的解析邏輯
        df, error = parse_contents(contents, filename)
        
        # 產生完成信號 (時間戳)
        finish_signal = f"DONE_{time.time()}"
        
        if error:
            return dbc.Alert(f"錯誤: {error}", color="danger"), finish_signal

        # --- 運算邏輯 (保持原樣，但因 df 已標準化，可直接使用) ---
        total_profit = df['損益試算'].sum()
        total_cost = df['買進金額'].sum()
        # 避免分母為 0
        total_roi = (df['賣出金額'].sum() / total_cost - 1) if total_cost != 0 else 0

        stock_grp = df.groupby('商品')[['買進金額', '賣出金額', '損益試算']].sum().reset_index()
        stock_grp['報酬率'] = stock_grp.apply(lambda row: (row['賣出金額'] / row['買進金額'] - 1) if row['買進金額'] != 0 else 0, axis=1)
        
        top_5_stocks = stock_grp.sort_values(by='損益試算', ascending=False).head(5)
        bottom_5_stocks = stock_grp.sort_values(by='損益試算', ascending=True).head(5)

        top_5_tx = df.sort_values(by='損益試算', ascending=False).head(5)
        bottom_5_tx = df.sort_values(by='損益試算', ascending=True).head(5)

        df_time = df.set_index('成交日期').sort_index()
        monthly_perf = df_time.resample('ME')[['損益試算']].sum() # pandas新版建議使用 'ME' 代替 'M'
        monthly_perf.index = monthly_perf.index.strftime('%Y-%m')
        quarterly_perf = df_time.resample('QE')[['損益試算']].sum() # pandas新版建議使用 'QE' 代替 'Q'
        quarterly_perf.index = quarterly_perf.index.strftime('%Y-Q%q')

        def fmt_df(d, m_cols, p_cols):
            d_f = d.copy()
            for c in m_cols: 
                if c in d_f: d_f[c] = d_f[c].apply(format_currency)
            for c in p_cols: 
                if c in d_f: d_f[c] = d_f[c].apply(format_percent)
            if '成交日期' in d_f: 
                # 檢查是否為 datetime 物件，如果是則格式化，否則保留字串
                if pd.api.types.is_datetime64_any_dtype(d_f['成交日期']):
                    d_f['成交日期'] = d_f['成交日期'].dt.strftime('%Y-%m-%d')
            return d_f

        def create_card(title, value, is_money=True):
            color_class = "text-white"
            if is_money and isinstance(value, (int, float)):
                if value > 0: color_class = "text-danger" 
                elif value < 0: color_class = "text-info"
                val_str = f"${value:,.0f}"
            elif not is_money and isinstance(value, float):
                val_str = f"{value:.2%}"
                if value > 0: color_class = "text-danger"
                else: color_class = "text-info"
            else:
                val_str = str(value)
            return dbc.Card([
                dbc.CardBody([
                    html.H6(title, className="card-subtitle mb-2 text-muted"),
                    html.H3(val_str, className=f"card-title {color_class}"),
                ])
            ], className="mb-4")

        summary = dbc.Row([
            dbc.Col(create_card("總獲利金額", total_profit), width=4),
            dbc.Col(create_card("總投入成本", total_cost), width=4),
            dbc.Col(create_card("總投資報酬率", total_roi, is_money=False), width=4),
        ])

        tabs = dbc.Tabs([
            dbc.Tab(label="個股排行榜", children=[
                dbc.Row([
                    dbc.Col([html.H5("🔥 獲利 Top 5", className="mt-3 text-center text-danger"), 
                             generate_table(fmt_df(top_5_stocks, ['損益試算'], ['報酬率']), ['商品', '損益試算', '報酬率'])], width=6),
                    dbc.Col([html.H5("❄️ 虧損 Top 5", className="mt-3 text-center text-info"), 
                             generate_table(fmt_df(bottom_5_stocks, ['損益試算'], ['報酬率']), ['商品', '損益試算', '報酬率'])], width=6)
                ])
            ]),
            dbc.Tab(label="單筆排行榜", children=[
                dbc.Row([
                    dbc.Col([html.H5("🚀 單筆獲利王", className="mt-3 text-center"), 
                             generate_table(fmt_df(top_5_tx, ['損益試算'], ['單筆報酬率']), ['成交日期', '商品', '損益試算', '單筆報酬率'])], width=6),
                    dbc.Col([html.H5("📉 單筆虧損王", className="mt-3 text-center"), 
                             generate_table(fmt_df(bottom_5_tx, ['損益試算'], ['單筆報酬率']), ['成交日期', '商品', '損益試算', '單筆報酬率'])], width=6)
            ])
        ]),
        dbc.Tab(label="週期趨勢", children=[
            dbc.Row([
                dbc.Col(dcc.Graph(figure=plot_period_bar(monthly_perf, "逐月損益")), width=6),
                dbc.Col(dcc.Graph(figure=plot_period_bar(quarterly_perf, "逐季損益")), width=6)
            ], className="mt-3")
        ]),
    ], className="mt-3")

        # 這裡將 UI 和 信號 一起回傳
        return html.Div([summary, tabs]), finish_signal

    except Exception as e:
        print(traceback.format_exc())
        return dbc.Alert(f"系統錯誤: {str(e)}", color="danger"), f"ERROR_{time.time()}"

# 2. Client-side Logic (JavaScript)
# 邏輯：監聽 last_modified (開始信號) 與 signal (結束信號)
app.clientside_callback(
    """
    function(last_modified, signal, filename) {
        console.log("JS Triggered. Signal:", signal, "LastMod:", last_modified);

        if (window.lastProcessedUpload === undefined) window.lastProcessedUpload = null;
        if (window.lastProcessedSignal === undefined) window.lastProcessedSignal = null;

        var container = document.getElementById('progress-section');
        var textDiv = document.getElementById('loading-text-display');
        var barDiv = document.getElementById('progress-bar-inner');
        var contentWrapper = document.getElementById('content-wrapper');

        // --- 邏輯 A: 檢查是否有「新的完成信號」 ---
        if (signal && signal !== window.lastProcessedSignal) {
            console.log(">>> FINISH SIGNAL RECEIVED");
            window.lastProcessedSignal = signal;
            
            // 停止計時器
            if (window.uploadTimer) clearInterval(window.uploadTimer);
            
            // 強制 100%
            if (textDiv) textDiv.innerText = '解析完成！ 100%';
            if (barDiv) barDiv.style.width = '100%';
            
            // 延遲顯示結果
            setTimeout(function(){
                if (container) container.style.display = 'none';
                if (contentWrapper) {
                    contentWrapper.style.display = 'block';
                    setTimeout(() => { contentWrapper.style.opacity = '1'; }, 50);
                }
            }, 500);
            
            return {'display': 'block'};
        }

        // --- 邏輯 B: 檢查是否有「新的上傳」 ---
        if (last_modified && last_modified !== window.lastProcessedUpload) {
            console.log(">>> UPLOAD DETECTED");
            window.lastProcessedUpload = last_modified;
            
            // UI 重置
            if (contentWrapper) {
                contentWrapper.style.opacity = '0';
                contentWrapper.style.display = 'none';
            }
            if (container) container.style.display = 'block';
            if (barDiv) barDiv.style.width = '0%';
            
            // 啟動計時器 (0% -> 90%)
            if (window.uploadTimer) clearInterval(window.uploadTimer);
            var percent = 0;
            window.targetPercent = 90; 
            
            window.uploadTimer = setInterval(function() {
                if (percent < window.targetPercent) {
                    percent += 1;
                    if (textDiv) textDiv.innerText = '正在載入 "' + (filename || '檔案') + '" ... ' + percent + '%';
                    if (barDiv) barDiv.style.width = percent + '%';
                }
            }, 30);
            
            return {'display': 'block'};
        }

        return window.dash_clientside.no_update;
    }
    """,
    Output('progress-section', 'style'),
    [Input('upload-data', 'last_modified'), 
     Input('signal-store', 'data')],
    [State('upload-data', 'filename')]
)

if __name__ == '__main__':
    app.run_server(debug=False)
