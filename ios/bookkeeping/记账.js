/*
 * Copyright (c) iGroup.
 * All rights reserved.
 */
/**
 * 截图文字记账：确认识别结果后保存独立的本地流水文件。
 * @author Kai
 * @date 2026/10/15 08:54
 * @description 接收快捷指令 OCR 文本，支持人工修正、重复提醒和月度查看。
 */

/** 本地账本目录；每笔独立保存，避免覆盖其他流水。 */
const fm = FileManager.local();
const directory = fm.joinPath(fm.documentsDirectory(), "BookkeepingV1");

/**
 * 展示提示或选择操作。
 * @param {string} title 提示标题
 * @param {string} message 提示内容
 * @param {string[]} actions 操作名称
 * @return {Promise<number>} 操作索引，取消返回 -1
 * @author Kai
 * @date 2026/10/15 08:54
 */
async function prompt(title, message, actions = ["好"]) {
    const alert = new Alert();
    alert.title = title;
    alert.message = message;
    actions.forEach(action => alert.addAction(action));
    alert.addCancelAction("取消");
    return await alert.presentAlert();
}

/**
 * 提取金额候选，只接受实付标签或带货币符号的数字。
 * @param {string} text 截图识别文字
 * @return {string[]} 按优先级排列的金额候选
 * @author Kai
 * @date 2026/10/15 08:54
 */
function amounts(text) {
    // 实付优先；货币符号仅作为待人工确认的候选，不取订单号等裸数字。
    const normalized = text.replace(/，/g, ",").replace(/,/g, "");
    const patterns = [
        /(?:实付款|实际支付|实付金额|实付|付款金额|支付金额|扣款金额|退款金额)\s*[:：]?\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)/g,
        /[¥￥]\s*(-?\d+(?:\.\d{1,2})?)/g
    ];
    return [...new Set(patterns.flatMap(pattern =>
        Array.from(normalized.matchAll(pattern), match => Math.abs(Number(match[1])).toFixed(2))
    ))];
}

/**
 * 读取有效流水，损坏文件会阻止继续写入并提示用户。
 * @return {object[]} 已保存流水
 * @author Kai
 * @date 2026/10/15 08:54
 */
function records() {
    return fm.listContents(directory).filter(name => name.endsWith(".json"))
        .map(name => JSON.parse(fm.readString(fm.joinPath(directory, name))));
}

/**
 * 执行识别、确认和记账；无输入时提供账本菜单。
 * @return {Promise<void>} 完成用户选择的账本操作
 * @author Kai
 * @date 2026/10/15 08:54
 */
async function main() {
    if (!fm.fileExists(directory)) fm.createDirectory(directory, true);
    // 快捷指令传纯文字；同时支持字典的 text 字段以及分享文本。
    const parameter = args.shortcutParameter;
    let text = typeof parameter === "string" ? parameter : String(parameter?.text || "");
    if (!text) text = (args.plainTexts || []).join("\n");
    if (!text.trim()) {
        const choice = await prompt("记账", "账本保存在本机 Scriptable 文档目录。", ["手动记账", "本月账本", "导出全部 JSON"]);
        if (choice < 0) return;
        if (choice === 1) {
            const month = localDate().slice(0, 7);
            const rows = records().filter(row => row.date.startsWith(month));
            const total = rows.reduce((sum, row) => sum + (row.type === "退款" ? -row.cents : row.cents), 0);
            await QuickLook.present(`${month} 净支出：¥${(total / 100).toFixed(2)}\n\n` + rows.map(row =>
                `${row.date} ${row.type} ¥${(row.cents / 100).toFixed(2)} ${row.merchant} · ${row.channel}`
            ).join("\n"));
            return;
        }
        if (choice === 2) {
            const path = fm.joinPath(fm.temporaryDirectory(), "账本备份.json");
            fm.writeString(path, JSON.stringify(records(), null, 4));
            await ShareSheet.present([path]);
            return;
        }
    }
    const candidates = amounts(text);
    // 渠道和付款账户分别判断，淘宝支付宝付款仍是一笔消费。
    const channel = ["淘宝", "京东", "拼多多", "滴滴", "抖音", "微信", "支付宝"].find(name => text.includes(name)) || "其他";
    const account = ["支付宝", "微信", "银行卡"].find(name => text.includes(name)) || "未知";
    const category = /滴滴|打车|出租车/.test(text) ? "交通" : /餐|外卖|咖啡|奶茶/.test(text) ? "餐饮" : "其他";
    // 未付款页面和退款页面明确提示，所有识别结果均由用户确认。
    const warning = /待付款|待支付|支付失败|已取消/.test(text) ? "⚠️ 可能尚未付款，请核实。\n" : "";
    const form = new Alert();
    form.title = "确认记账";
    form.message = warning + (candidates.length ? `金额候选：${candidates.join(" / ")}\n` : "未识别金额，请手动填写。\n") + "日期默认为今天；退款请将类型填写为退款。\n" + text.slice(0, 450);
    form.addTextField("金额（人民币）", candidates[0] || "");
    form.addTextField("商户 / 商品", "");
    form.addTextField("分类", category);
    form.addTextField("购买渠道", channel);
    form.addTextField("支付账户", account);
    form.addTextField("业务日期 YYYY-MM-DD", localDate());
    form.addTextField("类型：支出 / 退款", /退款成功|已退款/.test(text) ? "退款" : "支出");
    form.addAction("保存");
    form.addCancelAction("取消");
    if (await form.presentAlert() < 0) return;
    const amount = form.textFieldValue(0).trim();
    const date = form.textFieldValue(5).trim();
    const type = form.textFieldValue(6).trim();
    const parsedDate = new Date(`${date}T12:00:00`);
    if (!/^\d+(\.\d{1,2})?$/.test(amount) || Number(amount) <= 0 ||
        !/^\d{4}-\d{2}-\d{2}$/.test(date) || isNaN(parsedDate.getTime()) || localDate(parsedDate) !== date ||
        !["支出", "退款"].includes(type)) {
        await prompt("未保存", "金额需大于零且最多两位小数；日期须有效；类型须为支出或退款。请重新运行。");
        return;
    }
    const row = {
        // 整数分存金额；createdAt 是记录创建时间，date 是用户确认的交易发生日期。
        id: UUID.string(), cents: Math.round(Number(amount) * 100), date, type,
        merchant: form.textFieldValue(1).trim() || "未填写",
        category: form.textFieldValue(2).trim() || "其他",
        channel: form.textFieldValue(3).trim() || "其他",
        account: form.textFieldValue(4).trim() || "未知",
        createdAt: new Date().toISOString()
    };
    // 跨渠道同日同金额只能判断为疑似重复，允许用户确认继续保存。
    if (records().some(old => old.date === row.date && old.cents === row.cents && old.type === row.type)) {
        if (await prompt("疑似重复", "当天已有相同金额和类型的流水。请确认不是同一笔消费。", ["仍然保存"]) < 0) return;
    }
    fm.writeString(fm.joinPath(directory, `${row.id}.json`), JSON.stringify(row, null, 4));
    Script.setShortcutOutput(`已保存：${row.type} ¥${amount} · ${row.channel}`);
    await prompt("已保存", `${row.date} ${row.type} ¥${amount}\n${row.merchant} · ${row.category}`);
}

/**
 * 格式化本机日期，避免 UTC 时差改变交易日期。
 * @param {Date} date 业务发生日期，默认当前时间
 * @return {string} YYYY-MM-DD 日期
 * @author Kai
 * @date 2026/10/15 08:54
 */
function localDate(date = new Date()) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

// 失败时展示错误，不将异常或取消操作报告为记账成功。
try {
    await main();
} catch (error) {
    await prompt("记账失败", String(error));
}
Script.complete();
