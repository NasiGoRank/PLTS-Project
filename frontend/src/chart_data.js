function numericValues(values) {
  if (!Array.isArray(values)) return [];
  return values.map((value) => {
    if (value === null || value === undefined || value === "" || value === "-") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  });
}

function makeSeries({ labels, values, unit, kind, title, caption, reason }) {
  const safeLabels = Array.isArray(labels) ? labels.map(String) : [];
  const safeValues = numericValues(values);
  const available = safeLabels.length > 0
    && safeLabels.length === safeValues.length
    && safeValues.some((value) => value !== null);

  return {
    available,
    labels: available ? safeLabels : [],
    values: available ? safeValues : [],
    unit,
    kind,
    title,
    caption,
    reason: available ? null : reason,
  };
}

function chartSeries(chart, options) {
  return makeSeries({
    ...options,
    labels: chart?.labels,
    values: chart?.values,
  });
}

function trimTrailingMissing(chart) {
  const labels = Array.isArray(chart?.labels) ? chart.labels : [];
  const values = numericValues(chart?.values);
  let lastRecordedIndex = values.length - 1;
  while (lastRecordedIndex >= 0 && values[lastRecordedIndex] === null) {
    lastRecordedIndex -= 1;
  }
  return {
    labels: labels.slice(0, lastRecordedIndex + 1),
    values: values.slice(0, lastRecordedIndex + 1),
  };
}

function xySeries(chart, options) {
  return makeSeries({
    ...options,
    labels: chart?.x,
    values: chart?.y,
  });
}

function latestNestedSeries(group) {
  const entries = Object.entries(group?.series || {});
  if (!entries.length) return { key: null, data: null };
  entries.sort(([left], [right]) => left.localeCompare(right));
  const [key, data] = entries.at(-1);
  const values = data?.y?.y_data || data?.y?.y_data_elec || data?.y;
  return { key, data: { labels: data?.x, values } };
}

function unavailable({ unit, kind = "bar", title, reason }) {
  return makeSeries({ unit, kind, title, reason });
}

export function getEnergySeries(location, period) {
  const source = location?.source;
  const titleByPeriod = {
    today: "Today's production curve",
    month: "Daily energy this month",
    year: "Monthly energy this year",
  };
  const title = titleByPeriod[period] || "Energy history";

  if (source === "huawei") {
    if (period === "today") {
      return makeSeries({
        labels: location?.daily_power_5min?.x,
        values: location?.daily_power_5min?.generation_power_kw,
        unit: "kW",
        kind: "bar",
        title,
        caption: location?.daily_power_5min?.date || "5-minute production power",
        reason: "Today's Huawei power curve is unavailable for this station.",
      });
    }

    const chart = period === "month"
      ? location?.energy_charts?.daily
      : location?.energy_charts?.monthly;
    return chartSeries(trimTrailingMissing(chart), {
      unit: "kWh",
      kind: "bar",
      title,
      caption: period === "month" ? "Energy generated on each day" : "Energy generated in each month",
      reason: period === "month"
        ? "Monthly energy history is not provided for this Huawei station yet."
        : "Yearly energy history is not provided for this Huawei station yet.",
    });
  }

  if (source === "kehua") {
    const charts = location?.site?.charts || {};
    if (period === "today") {
      return xySeries(charts.daily_generation, {
        unit: "kWh",
        kind: "bar",
        title,
        caption: "Hourly generation reported by Kehua",
        reason: "Today's Kehua energy history is unavailable.",
      });
    }

    const dimension = period === "month" ? "month_daily" : "year_monthly";
    const nested = latestNestedSeries(charts.company_power_trends?.[dimension]);
    if (nested.data) {
      return chartSeries(nested.data, {
        unit: charts.company_power_trends?.[dimension]?.unit || (period === "year" ? "MWh" : "kWh"),
        kind: "bar",
        title,
        caption: nested.key || (period === "month" ? "Daily generation" : "Monthly generation"),
        reason: "Kehua energy history is unavailable.",
      });
    }

    return period === "month"
      ? xySeries(charts.monthly_generation, {
        unit: "kWh",
        kind: "bar",
        title,
        caption: "Daily generation reported by Kehua",
        reason: "Monthly Kehua energy history is unavailable.",
      })
      : unavailable({ unit: "MWh", title, reason: "Yearly Kehua energy history is unavailable." });
  }

  return unavailable({ unit: "kWh", title, reason: "Energy history is unavailable for this platform." });
}

export function getRevenueSeries(location, period) {
  const unit = location?.income_currency || (location?.source === "huawei" ? "IDR" : "Currency");
  const config = {
    month: {
      chart: trimTrailingMissing(location?.revenue_charts?.daily),
      title: "Daily revenue this month",
      caption: "Revenue through the latest reported day",
    },
    year: {
      chart: location?.revenue_charts?.monthly,
      title: "Monthly revenue this year",
      caption: "Revenue recorded in each month",
    },
    lifetime: {
      chart: location?.revenue_charts?.yearly,
      title: "Revenue by year",
      caption: "Available lifetime revenue history",
    },
  }[period];

  if (location?.source !== "huawei") {
    return unavailable({
      unit,
      title: config?.title || "Revenue history",
      reason: "Kehua does not provide a historical revenue series for this station.",
    });
  }

  return chartSeries(config?.chart, {
    unit,
    kind: "bar",
    title: config?.title || "Revenue history",
    caption: config?.caption,
    reason: period === "month"
      ? "Daily revenue history is not available for the selected Huawei month yet."
      : "Revenue history is unavailable for this period.",
  });
}
