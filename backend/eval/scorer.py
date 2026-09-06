def score(
    predictions: list[dict],
    ground_truth: list[dict],
    line_tolerance: int = 3,
) -> dict:
    matched_gt = set()
    matched_pred = set()

    for gi, gt in enumerate(ground_truth):
        for pi, pred in enumerate(predictions):
            if pi in matched_pred:
                continue

            if (
                gt["path"] == pred["file"]
                and abs(gt["line"] - pred["line_start"]) <= line_tolerance
            ):
                matched_gt.add(gi)
                matched_pred.add(pi)
                break

    tp = len(matched_pred)
    fp = len(predictions) - tp
    fn = len(ground_truth) - len(matched_gt)

    precision = (
        tp / len(predictions)
        if predictions
        else (1.0 if not ground_truth else 0.0)
    )

    recall = (
        tp / len(ground_truth)
        if ground_truth
        else 1.0
    )

    false_positive_rate = (
        fp / len(predictions)
        if predictions
        else 0.0
    )

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "false_positive_rate": false_positive_rate,
    }