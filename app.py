import base64
import io
import datetime
import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import mimetypes

# 強制修正 MIME types，避免 Render 誤判為 text/plain
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

# 初始化 Dash 應用程式，使用 Bootstrap 主題美化
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.FLATLY])
app.title = "投資組合績效追蹤系統"
server = app.server  # 用於部署 (如 Gunicorn)

# --- 輔助函式 ---

def parse_contents(contents, filename):
    """解析上傳的檔案內容"""
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    try:
        if 'csv' in filename:
            df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
        elif 'xls' in filename:
            df = pd.read_excel(io.BytesIO(decoded))
        else:
            return None, "不支援的檔案格式"
            
        # 資料預處理
        # 1. 日期轉換 (假設格式為 YYYYMMDD整數)
        df['成交日期'] = pd.to_datetime(df['成交日期'].astype(str), format='%Y%m%d', errors='coerce')
        
        # 2. 數值轉換
        numeric_cols = ['買進金額', '賣出金額', '損益試算', '成交數量', '成交價格']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 3. 計算單筆報酬率 (若無此欄位則計算，若有則沿用或重算)
        df['單筆報酬率'] = (df['賣出金額'] / df['買進金額']) - 1
        
        return df, None
    except Exception as e:
        return None, str(e)

def format_currency(value):
    """格式化金額 (千分位)"""
    return f"{int(value):,}"

def format_percent(value):
    """格式化百分比 (小數兩位)"""
    return f"{value:.2%}"

def generate_table(dataframe, display_cols=None):
    """生成 Dash DataTable"""
    if display_cols:
        df_display = dataframe[display_cols].copy()
    else:
        df_display = dataframe.copy()
        
    return dash_table.DataTable(
        data=df_display.to_dict('records'),
        columns=[{'name': i, 'id': i} for i in df_display.columns],
        style_table={'overflowX': 'auto'},
        style_header={
            'backgroundColor': 'rgb(230, 230, 230)',
            'fontWeight': 'bold'
        },
        style_cell={
            'textAlign': 'left',
            'padding': '10px',
            'font-family': 'sans-serif'
        },
        # 條件格式：正值紅色，負值綠色 (針對損益欄位)
        style_data_conditional=[
            {
                'if': {'filter_query': '{損益試算} > 0', 'column_id': '損益試算'},
                'color': '#d62728', 'fontWeight': 'bold'
            },
            {
                'if': {'filter_query': '{損益試算} < 0', 'column_id': '損益試算'},
                'color': '#2ca02c', 'fontWeight': 'bold'
            },
        ],
        page_size=10
    )

def plot_period_bar(df_resampled, title):
    """繪製週期性損益長條圖"""
    # 定義顏色：大於0紅色，小於0綠色
    colors = ['#d62728' if x > 0 else '#2ca02c' for x in df_resampled['損益試算']]
    
    fig = go.Figure(data=[
        go.Bar(
            x=df_resampled.index,
            y=df_resampled['損益試算'],
            marker_color=colors
        )
    ])
    fig.update_layout(
        title=title,
        yaxis_title="損益金額 (TWD)",
        template="plotly_white",
        margin=dict(l=40, r=40, t=40, b=40)
    )
    return fig

# --- App Layout (版面配置) ---

app.layout = dbc.Container([
    # 標題區
    dbc.Row([
        dbc.Col(html.H2("📊 投資組合績效追蹤系統 (Dash版)", className="text-center mb-4"), width=12)
    ], className="mt-4"),

    # 上傳區
    dbc.Row([
        dbc.Col([
            dcc.Upload(
                id='upload-data',
                children=html.Div(['拖拉檔案至此 或 ', html.A('點擊上傳 CSV/Excel')]),
                style={
                    'width': '100%', 'height': '60px', 'lineHeight': '60px',
                    'borderWidth': '1px', 'borderStyle': 'dashed',
                    'borderRadius': '5px', 'textAlign': 'center', 'margin': '10px'
                },
                multiple=False
            ),
            html.Div(id='output-file-status', className="text-center text-muted")
        ], width={"size": 8, "offset": 2})
    ]),

    html.Hr(),

    # 隱藏區：用於儲存處理後的 JSON 資料
    dcc.Store(id='stored-data'),

    # 內容顯示區
    dcc.Loading(
        id="loading-content",
        type="default",
        children=[html.Div(id='output-content')]
    ),
    
    # 頁尾
    dbc.Row(dbc.Col(html.Div("Designed for Financial Analysis", className="text-center text-muted mt-5 mb-3")))

], fluid=True)

# --- Callbacks (互動邏輯) ---

@app.callback(
    [Output('stored-data', 'data'),
     Output('output-file-status', 'children')],
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename')]
)
def update_output(contents, filename):
    if contents is None:
        return None, "等待檔案上傳..."
    
    df, error = parse_contents(contents, filename)
    if error:
        return None, f"錯誤: {error}"
    
    # 將 DataFrame 轉為 JSON 存入瀏覽器暫存 (處理 datetime 以便序列化)
    return df.to_json(date_format='iso', orient='split'), f"已成功載入: {filename}"

@app.callback(
    Output('output-content', 'children'),
    [Input('stored-data', 'data')]
)
def update_graphs(jsonified_cleaned_data):
    if jsonified_cleaned_data is None:
        return html.Div()
    
    # 從 JSON 還原 DataFrame
    df = pd.read_json(io.StringIO(jsonified_cleaned_data), orient='split')
    # 確保日期欄位為 datetime 物件
    df['成交日期'] = pd.to_datetime(df['成交日期'])

    # --- 邏輯運算 ---
    
    # 1. 總體摘要計算
    total_profit = df['損益試算'].sum()
    total_cost = df['買進金額'].sum()
    total_roi = (df['賣出金額'].sum() / total_cost) - 1

    # 2. 個股分析
    stock_grp = df.groupby('商品')[['買進金額', '賣出金額', '損益試算']].sum().reset_index()
    stock_grp['報酬率'] = (stock_grp['賣出金額'] / stock_grp['買進金額']) - 1
    
    top_5_stocks = stock_grp.sort_values(by='損益試算', ascending=False).head(5)
    bottom_5_stocks = stock_grp.sort_values(by='損益試算', ascending=True).head(5)

    # 3. 單筆分析
    top_5_tx = df.sort_values(by='損益試算', ascending=False).head(5)
    bottom_5_tx = df.sort_values(by='損益試算', ascending=True).head(5)

    # 4. 週期分析
    df_time = df.set_index('成交日期').sort_index()
    monthly_perf = df_time.resample('M')[['損益試算']].sum()
    monthly_perf.index = monthly_perf.index.strftime('%Y-%m')
    
    quarterly_perf = df_time.resample('Q')[['損益試算']].sum()
    quarterly_perf.index = quarterly_perf.index.strftime('%Y-Q%q')

    # --- 格式化數據供顯示 (轉換為字串) ---
    def format_df_display(d, money_cols, pct_cols):
        d_fmt = d.copy()
        for c in money_cols:
            if c in d_fmt.columns:
                d_fmt[c] = d_fmt[c].apply(format_currency)
        for c in pct_cols:
            if c in d_fmt.columns:
                d_fmt[c] = d_fmt[c].apply(format_percent)
        # 格式化日期
        if '成交日期' in d_fmt.columns:
            d_fmt['成交日期'] = d_fmt['成交日期'].dt.strftime('%Y-%m-%d')
        return d_fmt

    # --- 建構介面元件 ---
    
    # 摘要卡片
    cards = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H5("總獲利金額", className="card-title"),
                html.H3(f"${total_profit:,.0f}", className="text-danger" if total_profit > 0 else "text-success"),
            ])
        ], color="light", outline=True), width=4),
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H5("總投入成本", className="card-title"),
                html.H3(f"${total_cost:,.0f}"),
            ])
        ], color="light", outline=True), width=4),
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H5("總投資報酬率", className="card-title"),
                html.H3(f"{total_roi:.2%}", className="text-danger" if total_roi > 0 else "text-success"),
            ])
        ], color="light", outline=True), width=4),
    ], className="mb-4")

    # 分頁內容
    tabs = dbc.Tabs([
        # Tab 1: 個股排行榜
        dbc.Tab(label="🏆 個股排行榜", children=[
            dbc.Row([
                dbc.Col([
                    html.H5("🔥 最賺錢個股 Top 5", className="mt-3 text-center"),
                    generate_table(
                        format_df_display(top_5_stocks, ['損益試算'], ['報酬率']), 
                        ['商品', '損益試算', '報酬率']
                    )
                ], width=6),
                dbc.Col([
                    html.H5("💧 最賠錢個股 Top 5", className="mt-3 text-center"),
                    generate_table(
                        format_df_display(bottom_5_stocks, ['損益試算'], ['報酬率']), 
                        ['商品', '損益試算', '報酬率']
                    )
                ], width=6)
            ])
        ]),

        # Tab 2: 單筆排行榜
        dbc.Tab(label="⚡ 單筆排行榜", children=[
             dbc.Row([
                dbc.Col([
                    html.H5("🚀 單筆獲利王 Top 5", className="mt-3 text-center"),
                    generate_table(
                        format_df_display(top_5_tx, ['損益試算'], ['單筆報酬率']), 
                        ['成交日期', '商品', '損益試算', '單筆報酬率']
                    )
                ], width=6),
                dbc.Col([
                    html.H5("📉 單筆虧損王 Top 5", className="mt-3 text-center"),
                    generate_table(
                        format_df_display(bottom_5_tx, ['損益試算'], ['單筆報酬率']), 
                        ['成交日期', '商品', '損益試算', '單筆報酬率']
                    )
                ], width=6)
            ])
        ]),

        # Tab 3: 週期趨勢
        dbc.Tab(label="📈 週期趨勢", children=[
            dbc.Row([
                dbc.Col(dcc.Graph(figure=plot_period_bar(monthly_perf, "逐月獲利趨勢")), width=6),
                dbc.Col(dcc.Graph(figure=plot_period_bar(quarterly_perf, "逐季獲利趨勢")), width=6)
            ], className="mt-3")
        ]),
        
        # Tab 4: 原始資料檢視
        dbc.Tab(label="📋 原始資料", children=[
            html.Div(generate_table(format_df_display(df.head(50), ['買進金額', '賣出金額', '損益試算'], ['單筆報酬率'])), className="mt-3")
        ])
    ])

    return html.Div([cards, tabs])

if __name__ == '__main__':
    # debug=True 方便開發時除錯，部署時通常不影響，但建議改為 False

    app.run_server(debug=True)
