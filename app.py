import base64
import io
import time
import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import mimetypes

# 1. 強制修正 MIME Types (解決 Render 載入卡住問題)
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

# 2. 初始化 Dash 
# ★★★ 關鍵修正：必須加入 prevent_initial_callbacks="initial_duplicate" 才能使用多重 Output ★★★
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.DARKLY],
    prevent_initial_callbacks="initial_duplicate" 
)
app.title = "對帳單解析"

# 3. 暴露 server 變數給 Gunicorn (部署必備)
server = app.server

# 4. 星雲設計系統 CSS
nebula_styles = html.Style('''
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
        transition: width 0.1s linear;
    }
    .loading-text {
        color: var(--neon-blue);
        font-family: monospace;
        margin-bottom: 5px;
    }
    /* 表格樣式優化 */
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
    /* 分頁標籤樣式 */
    .nav-tabs .nav-link.active {
        background-color: var(--card-bg) !important;
        border-color: var(--neon-blue) !important;
        color: var(--neon-blue) !important;
    }
    .nav-tabs .nav-link {
        color: #888 !important;
    }
''')

# --- 邏輯運算函式 ---
def parse_contents(contents, filename):
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    try:
        if 'csv' in filename:
            df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
        elif 'xls' in filename:
            df = pd.read_excel(io.BytesIO(decoded))
        else:
            return None, "不支援的檔案格式"
        
        # 模擬運算延遲 (為了讓動畫跑完)
        time.sleep(1.5)
            
        df['成交日期'] = pd.to_datetime(df['成交日期'].astype(str), format='%Y%m%d', errors='coerce')
        numeric_cols = ['買進金額', '賣出金額', '損益試算', '成交數量', '成交價格']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        if '買進金額' in df.columns and '賣出金額' in df.columns:
            df['單筆報酬率'] = (df['賣出金額'] / df['買進金額']) - 1
        return df, None
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
    # 霓虹配色：紅 vs 青
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
    nebula_styles,
    
    dbc.Row([
        dbc.Col(html.H2("對帳單解析", className="text-center mt-5 mb-4 nebula-title"), width=12)
    ]),

    # 上傳區
    dbc.Row([
        dbc.Col([
            dcc.Upload(
                id='upload-data',
                children=html.Div([
                    '拖拉檔案至此 或 ', 
                    html.Span('點擊上傳 CSV', style={'textDecoration': 'underline', 'fontWeight': 'bold'})
                ]),
                style={
                    'width': '100%', 'height': '80px', 'lineHeight': '80px',
                    'borderWidth': '1px', 'borderStyle': 'dashed',
                    'borderRadius': '10px', 'textAlign': 'center', 'margin': '10px'
                },
                className='upload-box',
                multiple=False
            ),
            
            # 動態進度條
            html.Div([
                html.Div(id='loading-text-display', className='loading-text', children='準備中...'),
                html.Div(html.Div(id='progress-bar-inner', className='progress-bar-nebula'), 
                         style={'width': '100%', 'backgroundColor': '#1a1a2e', 'borderRadius': '2px'})
            ], id='progress-section', className='progress-container'),
            
        ], width={"size": 8, "offset": 2})
    ]),

    html.Hr(style={'borderColor': 'rgba(255,255,255,0.1)'}),

    # 結果輸出區
    html.Div(id='output-content')

], fluid=True, style={'minHeight': '100vh'})

# --- Callbacks ---

# 1. 前端動畫 JS (Client-side)
app.clientside_callback(
    """
    function(contents, filename) {
        if (!contents) {
            return {'display': 'none'};
        }
        
        var container = document.getElementById('progress-section');
        if (container) container.style.display = 'block';

        var percent = 0;
        var textDiv = document.getElementById('loading-text-display');
        var barDiv = document.getElementById('progress-bar-inner');
        
        if (window.uploadTimer) clearInterval(window.uploadTimer);
        
        // 模擬 0% -> 99% 的跑條
        window.uploadTimer = setInterval(function() {
            if (percent < 99) {
                percent += 1;
                if (textDiv) textDiv.innerText = '正在載入 "' + filename + '" ... ' + percent + '%';
                if (barDiv) barDiv.style.width = percent + '%';
            }
        }, 20); // 速度設定
        
        return {'display': 'block'};
    }
    """,
    Output('progress-section', 'style'),
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename')]
)

# 2. 後端 Python 處理
@app.callback(
    [Output('output-content', 'children'),
     Output('progress-section', 'style', allow_duplicate=True)], 
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename')],
    prevent_initial_call=True
)
def update_output(contents, filename):
    if contents is None:
        return html.Div(), {'display': 'none'}
    
    df, error = parse_contents(contents, filename)
    
    if error:
        return dbc.Alert(f"錯誤: {error}", color="danger"), {'display': 'none'}

    # 運算
    total_profit = df['損益試算'].sum()
    total_cost = df['買進金額'].sum()
    total_roi = (df['賣出金額'].sum() / total_cost) - 1

    stock_grp = df.groupby('商品')[['買進金額', '賣出金額', '損益試算']].sum().reset_index()
    stock_grp['報酬率'] = (stock_grp['賣出金額'] / stock_grp['買進金額']) - 1
    top_5_stocks = stock_grp.sort_values(by='損益試算', ascending=False).head(5)
    bottom_5_stocks = stock_grp.sort_values(by='損益試算', ascending=True).head(5)

    df['單筆報酬率'] = (df['賣出金額'] / df['買進金額']) - 1
    top_5_tx = df.sort_values(by='損益試算', ascending=False).head(5)
    bottom_5_tx = df.sort_values(by='損益試算', ascending=True).head(5)

    df_time = df.set_index('成交日期').sort_index()
    monthly_perf = df_time.resample('M')[['損益試算']].sum()
    monthly_perf.index = monthly_perf.index.strftime('%Y-%m')
    quarterly_perf = df_time.resample('Q')[['損益試算']].sum()
    quarterly_perf.index = quarterly_perf.index.strftime('%Y-Q%q')

    def fmt_df(d, m_cols, p_cols):
        d_f = d.copy()
        for c in m_cols: 
            if c in d_f: d_f[c] = d_f[c].apply(format_currency)
        for c in p_cols: 
            if c in d_f: d_f[c] = d_f[c].apply(format_percent)
        if '成交日期' in d_f: d_f['成交日期'] = d_f['成交日期'].dt.strftime('%Y-%m-%d')
        return d_f

    def create_card(title, value, is_money=True):
        color_class = "text-white"
        if is_money and isinstance(value, (int, float)):
            if value > 0: color_class = "text-danger" 
            elif value < 0: color_class = "text-info" # 青色代表賠
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

    # 構建 UI
    summary_section = dbc.Row([
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

    return html.Div([summary_section, tabs]), {'display': 'none'}

if __name__ == '__main__':
    app.run_server(debug=False)
