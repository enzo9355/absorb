"""LightGBM training and out-of-sample evaluation."""

from stock_papi.quant.constants import MODEL_FEATURES


def run_ai_engine(
    frame, *, add_prediction_target, build_time_splits,
    score_oos_predictions, pd, np, logger,
):
    try:
        from lightgbm import LGBMClassifier

        training = add_prediction_target(frame).dropna(
            subset=MODEL_FEATURES + ["FUTURE_RET_5", "T"]
        )
        if len(training) < 100 or training["T"].nunique() < 2:
            return None
        oos_prob = pd.Series(np.nan, index=training.index, dtype=float)
        for train_index, test_index in build_time_splits(len(training)):
            fold = training.iloc[train_index]
            if fold["T"].nunique() < 2:
                continue
            model = LGBMClassifier(
                n_estimators=80, learning_rate=0.05, max_depth=4,
                random_state=42, verbose=-1,
            )
            model.fit(fold[MODEL_FEATURES], fold["T"].astype(int))
            oos_prob.iloc[test_index] = model.predict_proba(
                training.iloc[test_index][MODEL_FEATURES]
            )[:, 1]
        valid = oos_prob.notna()
        if valid.sum() < 30:
            return None
        metrics = score_oos_predictions(
            training.loc[valid, "FUTURE_RET_5"], oos_prob.loc[valid]
        )
        final_model = LGBMClassifier(
            n_estimators=80, learning_rate=0.05, max_depth=4,
            random_state=42, verbose=-1,
        )
        final_model.fit(training[MODEL_FEATURES], training["T"].astype(int))
        latest_probability = final_model.predict_proba(
            frame.iloc[[-1]][MODEL_FEATURES]
        )[0, 1]
        frame["AI_P"] = np.nan
        frame.loc[oos_prob.loc[valid].index, "AI_P"] = oos_prob.loc[valid] * 100
        frame.loc[frame.index[-1], "AI_P"] = latest_probability * 100
        feature_names = {
            "MA_5": "5日均線動能", "MA20": "月線趨勢支撐",
            "RET_1": "單日反轉動能", "RET_5": "5日價格動能",
            "RET_20": "月報酬動能", "RSI": "RSI 強弱度",
            "Volat": "波動收斂度", "RANGE_PCT": "日內振幅",
            "VOL_RATIO": "成交量趨勢", "VOL_CHG": "成交量變化",
            "INST_NET_RATIO": "法人買賣超", "MARGIN_CHG": "融資變化",
            "SHORT_CHG": "融券變化", "MACD_OSC": "MACD 柱狀體動能",
            "K": "KD K值", "D": "KD D值",
            "MARKET_RET_1": "大盤單日動能", "MARKET_RET_5": "大盤5日動能",
            "MARKET_RET_20": "大盤月動能", "MARKET_VOL_20": "大盤波動度",
            "ETF50_RET_5": "0050五日動能", "STOCK_VS_MARKET_5": "個股相對大盤強度",
            "DATA_PRICE_DIFF_PCT": "資料源價差", "DATA_PRICE_WARNING": "資料品質警示",
        }
        importances = final_model.feature_importances_
        total_importance = max(float(importances.sum()), 1.0)
        metrics["top_features"] = [
            f"{feature_names.get(feature, feature)} (貢獻度: {importance / total_importance * 100:.1f}%)"
            for feature, importance in sorted(
                zip(MODEL_FEATURES, importances), key=lambda item: item[1], reverse=True
            )[:3]
        ]
        if metrics["trades"] == 0:
            metrics["conclusion"] = "⏸️ 訊號空窗：模型未發現高勝率進場點，選擇空手觀望。"
        elif metrics["strat_cum"] > metrics["bh_cum"]:
            metrics["conclusion"] = (
                "✅ 策略優勢：高報酬且風險控制優異。"
                if metrics["sharpe"] > 1 else "✅ 擊敗大盤：能創造超額報酬。"
            )
        else:
            metrics["conclusion"] = (
                "🛡️ 下檔保護：大跌時具備避險作用。"
                if metrics["mdd"] > -15 else "⚠️ 模型失真：容易追高殺低。"
            )
        return metrics
    except Exception as exc:
        logger.error("回測引擎錯誤: %s", exc)
        return None
