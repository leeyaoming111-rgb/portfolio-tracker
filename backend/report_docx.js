const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        ImageRun, Header, Footer, AlignmentType, BorderStyle, WidthType,
        ShadingType, VerticalAlign, PageBreak, HeadingLevel,
        TabStopType, TabStopPosition, PositionalTab,
        PositionalTabAlignment, PositionalTabRelativeTo, PositionalTabLeader
} = require("docx");

// ── Load data ─────────────────────────────────────────────────
const data = JSON.parse(fs.readFileSync(process.argv[2] || "report_data.json", "utf8"));
const commentary = process.argv[3] || data.commentary || "";
const outputPath = process.argv[4] || "reports/factsheet.docx";

// ── Brand ─────────────────────────────────────────────────────
const DEEP_PLUM = "4C1D6B";
const SOFT_PLUM = "6B2B9A";
const PALE_PLUM = "D4C4DF";
const ACCENT    = "7C3AED";
const INK       = "0A0A0A";
const WARM_GRAY = "7A7874";
const CHALK     = "E8E6E2";
const WHITE_HEX = "FFFFFF";
const TABLE_ALT = "F6F3F9";
const POS_GREEN = "16A34A";
const NEG_RED   = "DC2626";

// A4 in DXA
const PAGE_W = 11906;
const PAGE_H = 16838;
const MARGIN = 1020; // ~18mm
const CONTENT_W = PAGE_W - 2 * MARGIN; // 9866

const border = { style: BorderStyle.SINGLE, size: 1, color: PALE_PLUM };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorder = { style: BorderStyle.NONE, size: 0 };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };
const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };

// ── Helpers ───────────────────────────────────────────────────
function fmt(n, dp = 2) {
  if (n == null) return "\u2014";
  return n.toLocaleString("en-NZ", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function fmtPct(n) {
  if (n == null) return "\u2014";
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}
function pctColor(n) { return n >= 0 ? POS_GREEN : NEG_RED; }

function headerCell(text, width) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: { fill: DEEP_PLUM, type: ShadingType.CLEAR },
    borders, margins: cellMargins,
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text, bold: true, size: 15, font: "Arial", color: WHITE_HEX })] })]
  });
}
function dataCell(text, width, opts = {}) {
  const { bold, color, align, shading } = opts;
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: shading ? { fill: shading, type: ShadingType.CLEAR } : undefined,
    borders, margins: cellMargins,
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({ alignment: align || AlignmentType.CENTER,
      children: [new TextRun({ text: String(text), bold: !!bold, size: 15, font: "Arial",
        color: color || INK })] })]
  });
}
function labelCell(text, width, shading) {
  return dataCell(text, width, { bold: true, align: AlignmentType.LEFT, shading });
}
function detailRow(label, value) {
  return new TableRow({ children: [
    new TableCell({
      width: { size: Math.floor(CONTENT_W * 0.55), type: WidthType.DXA },
      borders: { ...noBorders, bottom: border }, margins: cellMargins,
      children: [new Paragraph({ children: [
        new TextRun({ text: label, size: 15, font: "Arial", color: WARM_GRAY })] })]
    }),
    new TableCell({
      width: { size: Math.floor(CONTENT_W * 0.45), type: WidthType.DXA },
      borders: { ...noBorders, bottom: border }, margins: cellMargins,
      children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [
        new TextRun({ text: value, size: 15, font: "Arial", bold: true, color: INK })] })]
    }),
  ]});
}

// ── Read images ───────────────────────────────────────────────
const chartImg = fs.readFileSync("chart_perf.png");
const markImg = fs.readFileSync("mark.png");

// ── Build sections ────────────────────────────────────────────
const pr = data.period_returns;
const bm = data.bm_returns;
const periods = ["MTD", "QTD", "YTD", "ITD"];
const periodLabels = ["MTD", "QTD", "YTD", "Since Inception"];

// Column widths for performance table
const perfLabelW = Math.floor(CONTENT_W * 0.28);
const perfColW = Math.floor((CONTENT_W - perfLabelW) / 4);
const perfCols = [perfLabelW, perfColW, perfColW, perfColW, CONTENT_W - perfLabelW - perfColW * 3];

const children = [];

// ── Header with mark + wordmark ──
children.push(new Paragraph({
  spacing: { after: 60 },
  children: [
    new ImageRun({ data: markImg, transformation: { width: 28, height: 28 }, type: "png" }),
    new TextRun({ text: "  leehong ", bold: true, size: 24, font: "Arial", color: DEEP_PLUM }),
    new TextRun({ text: "capital", size: 24, font: "Arial", color: WARM_GRAY }),
  ]
}));

// Title bar
children.push(new Paragraph({
  spacing: { after: 200 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: DEEP_PLUM, space: 4 } },
  children: [
    new TextRun({ text: `Monthly Factsheet  |  ${data.month_display}  |  AS OF ${data.as_of}`,
      size: 17, font: "Arial", color: WARM_GRAY }),
  ]
}));

// ── Hypothetical Growth of $10,000 ──
children.push(new Paragraph({
  spacing: { before: 100, after: 100 },
  children: [new TextRun({ text: "Hypothetical Growth of $10,000", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
}));

children.push(new Paragraph({
  spacing: { after: 40 },
  children: [new ImageRun({ data: chartImg, transformation: { width: 560, height: 216 }, type: "png" })]
}));

children.push(new Paragraph({
  spacing: { after: 200 },
  children: [new TextRun({
    text: "Past performance is not indicative of future results. Investment return and principal value will fluctuate.",
    size: 13, font: "Arial", color: WARM_GRAY, italics: true })]
}));

// ── Performance Table ──
children.push(new Paragraph({
  spacing: { before: 100, after: 100 },
  children: [new TextRun({ text: "Performance", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
}));

const perfRows = [
  // Header
  new TableRow({ children: [
    headerCell("", perfCols[0]),
    ...periodLabels.map((l, i) => headerCell(l, perfCols[i + 1])),
  ]}),
  // Fund returns
  new TableRow({ children: [
    labelCell("LeeHong Capital", perfCols[0], TABLE_ALT),
    ...periods.map((p, i) => dataCell(fmtPct(pr[p]), perfCols[i + 1],
      { color: pctColor(pr[p]), shading: TABLE_ALT })),
  ]}),
  // Benchmark
  new TableRow({ children: [
    labelCell("S&P 500 TR", perfCols[0]),
    ...periods.map((p, i) => dataCell(fmtPct(bm[p]), perfCols[i + 1])),
  ]}),
  // Alpha
  new TableRow({ children: [
    dataCell("Alpha", perfCols[0], { bold: true, align: AlignmentType.LEFT, shading: TABLE_ALT }),
    ...periods.map((p, i) => {
      const alpha = pr[p] - bm[p];
      return dataCell(fmtPct(alpha), perfCols[i + 1], { color: pctColor(alpha), shading: TABLE_ALT });
    }),
  ]}),
];

children.push(new Table({
  width: { size: CONTENT_W, type: WidthType.DXA },
  columnWidths: perfCols,
  rows: perfRows,
}));

// ── Calendar Year Returns ──
const calYears = Object.keys(data.cal_years).sort();
if (calYears.length > 0) {
  children.push(new Paragraph({
    spacing: { before: 200, after: 100 },
    children: [new TextRun({ text: "Calendar Year Returns", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
  }));

  const cyLabelW = Math.floor(CONTENT_W * 0.30);
  const cyColW = Math.floor((CONTENT_W - cyLabelW) / calYears.length);
  const cyCols = [cyLabelW, ...calYears.map((_, i) =>
    i < calYears.length - 1 ? cyColW : CONTENT_W - cyLabelW - cyColW * (calYears.length - 1))];

  children.push(new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: cyCols,
    rows: [
      new TableRow({ children: [headerCell("", cyCols[0]), ...calYears.map((y, i) => headerCell(y, cyCols[i+1]))] }),
      new TableRow({ children: [
        labelCell("LeeHong Capital", cyCols[0], TABLE_ALT),
        ...calYears.map((y, i) => dataCell(fmtPct(data.cal_years[y].portfolio), cyCols[i+1],
          { color: pctColor(data.cal_years[y].portfolio), shading: TABLE_ALT })),
      ]}),
      new TableRow({ children: [
        labelCell("S&P 500 TR", cyCols[0]),
        ...calYears.map((y, i) => dataCell(fmtPct(data.cal_years[y].benchmark), cyCols[i+1])),
      ]}),
    ],
  }));
}

// ── Fund Details ──
children.push(new Paragraph({
  spacing: { before: 200, after: 100 },
  children: [new TextRun({ text: "Fund Details", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
}));

const detCols = [Math.floor(CONTENT_W * 0.55), CONTENT_W - Math.floor(CONTENT_W * 0.55)];
children.push(new Table({
  width: { size: CONTENT_W, type: WidthType.DXA },
  columnWidths: detCols,
  rows: [
    detailRow("Fund Inception", "21 April 2026"),
    detailRow("Net Asset Value", `NZ$ ${fmt(data.latest_nav, 0)}`),
    detailRow("Holdings", String(data.num_holdings)),
    detailRow("Management Fee", "0.00%"),
    detailRow("Performance Fee", "0.00%"),
    detailRow("Benchmark", "S&P 500 Total Return"),
    detailRow("Base Currency", "NZD"),
    detailRow("Custodian", "Interactive Brokers"),
    detailRow("Fund Status", "Closed to general public"),
    detailRow("Minimum Investment", "None"),
  ],
}));

// ── PAGE BREAK ──
children.push(new Paragraph({ children: [new PageBreak()] }));

// ═══════════════════════════════════════════════════════════════
// PAGE 2
// ═══════════════════════════════════════════════════════════════

// ── Header repeat ──
children.push(new Paragraph({
  spacing: { after: 60 },
  children: [
    new ImageRun({ data: markImg, transformation: { width: 28, height: 28 }, type: "png" }),
    new TextRun({ text: "  leehong ", bold: true, size: 24, font: "Arial", color: DEEP_PLUM }),
    new TextRun({ text: "capital", size: 24, font: "Arial", color: WARM_GRAY }),
  ]
}));
children.push(new Paragraph({
  spacing: { after: 200 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: DEEP_PLUM, space: 4 } },
  children: [new TextRun({ text: `Monthly Factsheet  |  ${data.month_display}  |  Page 2`,
    size: 17, font: "Arial", color: WARM_GRAY })]
}));

// ── Asset Allocation ──
children.push(new Paragraph({
  spacing: { before: 100, after: 100 },
  children: [new TextRun({ text: "Asset Allocation", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
}));

const allocCols = [Math.floor(CONTENT_W * 0.65), CONTENT_W - Math.floor(CONTENT_W * 0.65)];
const allocRows = [
  new TableRow({ children: [headerCell("Category", allocCols[0]), headerCell("Weight", allocCols[1])] }),
];
Object.entries(data.allocation).forEach(([cat, pct], i) => {
  if (pct > 0) allocRows.push(new TableRow({ children: [
    labelCell(cat, allocCols[0], i % 2 === 0 ? TABLE_ALT : undefined),
    dataCell(pct.toFixed(1) + "%", allocCols[1], { shading: i % 2 === 0 ? TABLE_ALT : undefined }),
  ]}));
});
children.push(new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: allocCols, rows: allocRows }));

// ── Top Holdings ──
const topPos = (data.positions || []).sort((a, b) => (b.weight_pct || 0) - (a.weight_pct || 0)).slice(0, 10);
if (topPos.length > 0) {
  const topWeight = topPos.reduce((s, p) => s + (p.weight_pct || 0), 0);
  children.push(new Paragraph({
    spacing: { before: 200, after: 40 },
    children: [new TextRun({ text: "Top Holdings", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
  }));
  children.push(new Paragraph({
    spacing: { after: 100 },
    children: [new TextRun({
      text: `${topWeight.toFixed(1)}% of Total Portfolio  |  ${data.num_holdings} holdings`,
      size: 15, font: "Arial", color: WARM_GRAY })]
  }));

  const holdCols = [Math.floor(CONTENT_W * 0.70), CONTENT_W - Math.floor(CONTENT_W * 0.70)];
  const holdRows = [
    new TableRow({ children: [headerCell("Stock", holdCols[0]), headerCell("Weight", holdCols[1])] }),
  ];
  topPos.forEach((p, i) => {
    holdRows.push(new TableRow({ children: [
      labelCell((p.stock_name || p.code).toUpperCase(), holdCols[0], i % 2 === 0 ? TABLE_ALT : undefined),
      dataCell((p.weight_pct || 0).toFixed(2) + "%", holdCols[1], { shading: i % 2 === 0 ? TABLE_ALT : undefined }),
    ]}));
  });
  children.push(new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: holdCols, rows: holdRows }));
}

// ── Volatility Measures ──
const vol = data.volatility || {};
children.push(new Paragraph({
  spacing: { before: 200, after: 100 },
  children: [new TextRun({ text: "Volatility Measures", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
}));
children.push(new Table({
  width: { size: CONTENT_W, type: WidthType.DXA },
  columnWidths: detCols,
  rows: [
    detailRow("Beta", vol.beta != null ? String(vol.beta) : "\u2014"),
    detailRow("R\u00B2", vol.r_squared != null ? String(vol.r_squared) : "\u2014"),
    detailRow("Sharpe Ratio", vol.sharpe != null ? String(vol.sharpe) : "\u2014"),
    detailRow("Standard Deviation", vol.std_dev != null ? vol.std_dev + "%" : "\u2014"),
  ],
}));

// ── Fund Manager ──
children.push(new Paragraph({
  spacing: { before: 200, after: 100 },
  children: [new TextRun({ text: "Fund Manager", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
}));
children.push(new Paragraph({
  children: [
    new TextRun({ text: "Primary Manager: ", size: 16, font: "Arial", color: WARM_GRAY }),
    new TextRun({ text: "Yao Ming Lee (since April 2026)", bold: true, size: 16, font: "Arial", color: INK }),
  ]
}));

// ── Manager Commentary ──
if (commentary) {
  children.push(new Paragraph({
    spacing: { before: 240, after: 80 },
    children: [new TextRun({ text: "Manager Commentary", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
  }));
  children.push(new Paragraph({
    spacing: { after: 100 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 3, color: ACCENT, space: 2 } },
    children: [],
  }));
  commentary.split("\n\n").forEach(para => {
    if (para.trim()) {
      children.push(new Paragraph({
        spacing: { after: 120 },
        children: [new TextRun({ text: para.trim(), size: 17, font: "Arial", color: INK })],
      }));
    }
  });
}

// ── Disclaimer (page 3) ──
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(new Paragraph({
  spacing: { before: 100, after: 100 },
  children: [new TextRun({ text: "Important Information", bold: true, size: 20, font: "Arial", color: DEEP_PLUM })]
}));
children.push(new Paragraph({
  spacing: { after: 120 },
  children: [new TextRun({
    text: "This report is provided for informational purposes only and does not constitute an offer to sell or a solicitation of an offer to buy any securities. LeeHong Capital is an informal, unregistered investment fund operating in New Zealand. It is not registered under the Financial Markets Conduct Act 2013 (FMCA), and accordingly, the protections afforded to investors under the FMCA do not apply.",
    size: 15, font: "Arial", color: WARM_GRAY })]
}));
children.push(new Paragraph({
  spacing: { after: 120 },
  children: [new TextRun({
    text: "Past performance is not indicative of future results. Investing involves significant risk, including the possible loss of the entire amount invested. The S&P 500 Total Return Index is a market capitalisation-weighted index of 500 common stocks. It is not possible to invest directly in an index.",
    size: 15, font: "Arial", color: WARM_GRAY })]
}));

// ═══════════════════════════════════════════════════════════════
// DOCUMENT
// ═══════════════════════════════════════════════════════════════
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_W, height: PAGE_H },
        margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN },
      },
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          border: { top: { style: BorderStyle.SINGLE, size: 1, color: PALE_PLUM, space: 4 } },
          tabStops: [{ type: TabStopType.RIGHT, position: CONTENT_W }],
          children: [
            new TextRun({ text: "leehong capital", size: 13, font: "Arial", color: WARM_GRAY }),
            new TextRun({ text: "  |  private & confidential", size: 13, font: "Arial", color: PALE_PLUM }),
            new PositionalTab({ alignment: PositionalTabAlignment.RIGHT,
              relativeTo: PositionalTabRelativeTo.MARGIN, leader: PositionalTabLeader.NONE }),
            new TextRun({ text: `Report as of ${new Date().toLocaleDateString("en-NZ")}`,
              size: 13, font: "Arial", color: WARM_GRAY }),
          ]
        })]
      })
    },
    children,
  }],
});

// ── Write ─────────────────────────────────────────────────────
const dir = require("path").dirname(outputPath);
if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(outputPath, buffer);
  console.log(`\u2705 Factsheet generated: ${outputPath}`);
});
