using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace AIUsageBarHook
{
    internal static class Program
    {
        private static readonly DateTime UnixEpoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        private static readonly UTF8Encoding Utf8NoBom = new UTF8Encoding(false);

        private static int Main(string[] args)
        {
            try
            {
                Console.InputEncoding = Encoding.UTF8;
                Console.OutputEncoding = Utf8NoBom;
            }
            catch { }

            string mode = null;
            string customStatePath = null;

            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i].Trim();
                if (a.Equals("--claude", StringComparison.OrdinalIgnoreCase))
                    mode = "claude";
                else if (a.Equals("--agy", StringComparison.OrdinalIgnoreCase) || a.Equals("--antigravity", StringComparison.OrdinalIgnoreCase))
                    mode = "antigravity";
                else if (a.Equals("--state-path", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                    customStatePath = args[++i];
            }

            if (string.IsNullOrEmpty(mode))
                return 0;

            string raw;
            try
            {
                raw = Console.In.ReadToEnd();
            }
            catch
            {
                return 0;
            }

            if (string.IsNullOrWhiteSpace(raw))
                return 0;

            JavaScriptSerializer ser = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };
            Dictionary<string, object> payload;
            try
            {
                payload = ser.DeserializeObject(raw) as Dictionary<string, object>;
            }
            catch
            {
                return 0;
            }

            if (payload == null)
                return 0;

            string statePath = !string.IsNullOrEmpty(customStatePath)
                ? customStatePath
                : Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "AIUsageBar",
                    "quota_state.json");

            double now = NowUnix();

            try
            {
                if (Environment.GetEnvironmentVariable("AIUSAGEBAR_DEBUG") == "1")
                    WriteSafeDebugSchema(statePath, mode, payload, now, ser);
                if (mode == "claude")
                    HandleClaude(payload, statePath, now, ser);
                else
                    HandleAntigravity(payload, statePath, now, ser);
            }
            catch (Exception ex)
            {
                try
                {
                    string dir = Path.GetDirectoryName(statePath);
                    if (!string.IsNullOrEmpty(dir))
                    {
                        Directory.CreateDirectory(dir);
                        File.AppendAllText(
                            Path.Combine(dir, "hook_error.log"),
                            "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "] (" + mode + ") " + ex + Environment.NewLine,
                            Utf8NoBom);
                    }
                }
                catch { }
            }

            return 0;
        }

        private static void HandleClaude(
            Dictionary<string, object> payload,
            string statePath,
            double now,
            JavaScriptSerializer ser)
        {
            var modelDict = GetDict(payload, "model");
            string modelName = GetString(modelDict, "display_name") ?? GetString(modelDict, "id") ?? "";

            var ctxDict = GetDict(payload, "context_window");
            double? ctxUsed = ClampPct(GetDouble(ctxDict, "used_percentage"));

            var costDict = GetDict(payload, "cost");
            double? totalCost = GetDouble(costDict, "total_cost_usd");

            var rlDict = GetDict(payload, "rate_limits") ?? GetDict(payload, "rateLimits");
            Dictionary<string, object> session5h = ExtractClaudeLimit(
                GetDict(rlDict, "five_hour") ?? GetDict(rlDict, "fiveHour"), now);
            Dictionary<string, object> weekly = ExtractClaudeLimit(
                GetDict(rlDict, "seven_day") ?? GetDict(rlDict, "sevenDay"), now);
            Dictionary<string, object> weeklyFable = ExtractClaudeLimit(
                GetDict(rlDict, "seven_day_fable") ?? GetDict(rlDict, "sevenDayFable") ?? GetDict(rlDict, "fable"), now);

            var extraBuckets = new Dictionary<string, object>();
            if (rlDict != null)
            {
                foreach (var kv in rlDict)
                {
                    string lk = kv.Key.ToLowerInvariant();
                    if (lk == "five_hour" || lk == "fivehour" || lk == "seven_day" || lk == "sevenday")
                        continue;

                    if (lk == "model_scoped" || lk == "modelscoped")
                    {
                        var scopedFable = ExtractFableFromModelScoped(kv.Value, now);
                        if (scopedFable != null && weeklyFable == null)
                            weeklyFable = scopedFable;
                        continue;
                    }

                    var parsed = ExtractClaudeLimit(kv.Value as Dictionary<string, object>, now);
                    if (parsed != null)
                    {
                        if (lk.Contains("fable") && weeklyFable == null)
                            weeklyFable = parsed;
                        else if (!lk.Contains("fable"))
                            extraBuckets[kv.Key] = parsed;
                    }
                }
            }

            var patch = new Dictionary<string, object>
            {
                { "source", "claude_code_statusline" },
                { "updated_at", now }
            };
            if (!string.IsNullOrEmpty(modelName))
                patch["model"] = modelName;
            if (ctxUsed.HasValue)
                patch["context_used_pct"] = ctxUsed.Value;
            if (totalCost.HasValue)
                patch["total_cost_usd"] = totalCost.Value;
            if (weekly != null)
                patch["weekly"] = weekly;
            if (weeklyFable != null)
                patch["weekly_fable"] = weeklyFable;
            if (session5h != null)
                patch["session_5h"] = session5h;
            if (extraBuckets.Count > 0)
                patch["extra_buckets"] = extraBuckets;

            UpdateProviderState(statePath, "claude", patch, ser);

            var parts = new List<string>();
            if (!string.IsNullOrEmpty(modelName))
                parts.Add(modelName);
            if (ctxUsed.HasValue)
                parts.Add("Ctx " + Math.Round(ctxUsed.Value).ToString("0", CultureInfo.InvariantCulture) + "%");
            if (session5h != null)
            {
                double rem = Convert.ToDouble(session5h["remaining_pct"], CultureInfo.InvariantCulture);
                string cd = FormatCountdownCompact(GetDouble(session5h, "resets_at"), now);
                parts.Add("5h " + Math.Round(rem).ToString("0", CultureInfo.InvariantCulture) + "%" + (string.IsNullOrEmpty(cd) ? "" : " (" + cd + ")"));
            }
            if (weekly != null)
            {
                double rem = Convert.ToDouble(weekly["remaining_pct"], CultureInfo.InvariantCulture);
                string cd = FormatCountdownCompact(GetDouble(weekly, "resets_at"), now);
                parts.Add("7d " + Math.Round(rem).ToString("0", CultureInfo.InvariantCulture) + "%" + (string.IsNullOrEmpty(cd) ? "" : " (" + cd + ")"));
            }
            if (weeklyFable != null)
            {
                double rem = Convert.ToDouble(weeklyFable["remaining_pct"], CultureInfo.InvariantCulture);
                parts.Add("Fable " + Math.Round(rem).ToString("0", CultureInfo.InvariantCulture) + "%");
            }

            if (parts.Count > 0)
                Console.WriteLine(string.Join(" | ", parts));
        }

        private static Dictionary<string, object> ExtractClaudeLimit(Dictionary<string, object> obj, double now)
        {
            if (obj == null) return null;
            double? used = ClampPct(GetDouble(obj, "used_percentage") ?? GetDouble(obj, "usedPercentage") ?? GetDouble(obj, "utilization"));
            double? rem = ClampPct(GetDouble(obj, "remaining_percentage") ?? GetDouble(obj, "remainingPercentage"));
            if (!rem.HasValue)
            {
                double? frac = GetDouble(obj, "remaining_fraction") ?? GetDouble(obj, "remainingFraction");
                if (frac.HasValue)
                    rem = ClampPct(frac.Value <= 1.0 ? frac.Value * 100.0 : frac.Value);
            }
            if (!rem.HasValue && used.HasValue)
                rem = ClampPct(100.0 - used.Value);
            if (!used.HasValue && rem.HasValue)
                used = ClampPct(100.0 - rem.Value);
            if (!rem.HasValue)
                return null;

            double? resetsAt = ParseTimestamp(
                GetObj(obj, "resets_at") ?? GetObj(obj, "resetsAt") ?? GetObj(obj, "reset_time"),
                GetObj(obj, "reset_in_seconds"),
                now);
            return new Dictionary<string, object>
            {
                { "remaining_pct", rem.Value },
                { "used_pct", used.Value },
                { "resets_at", resetsAt.HasValue ? (object)resetsAt.Value : null }
            };
        }

        private static Dictionary<string, object> ExtractFableFromModelScoped(object scopedObj, double now)
        {
            if (scopedObj == null) return null;
            var dict = scopedObj as Dictionary<string, object>;
            if (dict != null)
            {
                foreach (var kv in dict)
                {
                    if (kv.Key.ToLowerInvariant().Contains("fable"))
                    {
                        var parsed = ExtractClaudeLimit(kv.Value as Dictionary<string, object>, now);
                        if (parsed != null) return parsed;
                    }
                }
                return null;
            }
            var arr = scopedObj as object[];
            if (arr != null)
            {
                foreach (var item in arr)
                {
                    var d = item as Dictionary<string, object>;
                    if (d == null) continue;
                    string id = (GetString(d, "model") ?? GetString(d, "name") ?? GetString(d, "id") ?? GetString(d, "bucket") ?? "").ToLowerInvariant();
                    if (id.Contains("fable"))
                    {
                        var parsed = ExtractClaudeLimit(d, now);
                        if (parsed != null) return parsed;
                    }
                }
            }
            return null;
        }

        private static void WriteSafeDebugSchema(
            string statePath,
            string mode,
            Dictionary<string, object> payload,
            double now,
            JavaScriptSerializer ser)
        {
            try
            {
                string dir = Path.GetDirectoryName(statePath);
                if (string.IsNullOrEmpty(dir)) return;
                Directory.CreateDirectory(dir);
                var dbg = ReadJsonDict(Path.Combine(dir, "hook_debug.json"), ser);
                var entry = new Dictionary<string, object>
                {
                    { "updated_at", now },
                    { "keys", new List<string>(payload.Keys) }
                };
                if (payload.ContainsKey("rate_limits")) entry["rate_limits"] = payload["rate_limits"];
                if (payload.ContainsKey("rateLimits")) entry["rateLimits"] = payload["rateLimits"];
                if (payload.ContainsKey("quota")) entry["quota"] = payload["quota"];
                if (payload.ContainsKey("cost")) entry["cost"] = payload["cost"];
                if (payload.ContainsKey("context_window")) entry["context_window"] = payload["context_window"];
                dbg[mode] = entry;
                WriteJsonAtomic(Path.Combine(dir, "hook_debug.json"), ser.Serialize(dbg));
            }
            catch { }
        }

        private static void HandleAntigravity(
            Dictionary<string, object> payload,
            string statePath,
            double now,
            JavaScriptSerializer ser)
        {
            var modelDict = GetDict(payload, "model");
            string modelName = GetString(modelDict, "display_name") ?? GetString(modelDict, "id") ?? "";
            string planTier = GetString(payload, "plan_tier");

            var rawQuota = GetDict(payload, "quota");
            var allBuckets = new Dictionary<string, object>();
            var parsedList = new List<Tuple<string, Dictionary<string, object>>>();

            if (rawQuota != null)
            {
                foreach (var kv in rawQuota)
                {
                    var parsed = ParseAgyBucket(kv.Key, kv.Value as Dictionary<string, object>, now);
                    if (parsed != null)
                    {
                        allBuckets[kv.Key] = parsed;
                        parsedList.Add(Tuple.Create(kv.Key, parsed));
                    }
                }
            }

            Dictionary<string, object> weekly = null;
            Dictionary<string, object> weeklyArgon = null;
            Dictionary<string, object> session5h = null;
            ClassifyAgyBuckets(parsedList, now, out weekly, out weeklyArgon, out session5h);

            var patch = new Dictionary<string, object>
            {
                { "source", "agy_cli_statusline" }
            };
            if (!string.IsNullOrEmpty(modelName))
                patch["model"] = modelName;
            if (!string.IsNullOrEmpty(planTier))
                patch["plan_tier"] = planTier;
            if (allBuckets.Count > 0)
            {
                patch["updated_at"] = now;
                patch["quota_updated_at"] = now;
                patch["all_buckets"] = allBuckets;
            }
            if (weekly != null)
                patch["weekly"] = weekly;
            if (weeklyArgon != null)
                patch["weekly_argon"] = weeklyArgon;
            if (session5h != null)
                patch["session_5h"] = session5h;

            UpdateProviderState(statePath, "antigravity", patch, ser);

            var parts = new List<string>();
            if (!string.IsNullOrEmpty(modelName))
                parts.Add(modelName);
            if (session5h != null)
            {
                double rem = Convert.ToDouble(session5h["remaining_pct"], CultureInfo.InvariantCulture);
                string cd = FormatCountdownCompact(GetDouble(session5h, "resets_at"), now);
                parts.Add("5h " + Math.Round(rem).ToString("0", CultureInfo.InvariantCulture) + "%" + (string.IsNullOrEmpty(cd) ? "" : " (" + cd + ")"));
            }
            if (weekly != null)
            {
                double rem = Convert.ToDouble(weekly["remaining_pct"], CultureInfo.InvariantCulture);
                string cd = FormatCountdownCompact(GetDouble(weekly, "resets_at"), now);
                parts.Add("7d " + Math.Round(rem).ToString("0", CultureInfo.InvariantCulture) + "%" + (string.IsNullOrEmpty(cd) ? "" : " (" + cd + ")"));
            }
            if (weeklyArgon != null)
            {
                double rem = Convert.ToDouble(weeklyArgon["remaining_pct"], CultureInfo.InvariantCulture);
                parts.Add("Argon " + Math.Round(rem).ToString("0", CultureInfo.InvariantCulture) + "%");
            }

            if (parts.Count > 0)
                Console.WriteLine(string.Join(" | ", parts));
        }

        private static Dictionary<string, object> ParseAgyBucket(string bucketId, Dictionary<string, object> obj, double now)
        {
            if (obj == null) return null;
            object disabledObj = GetObj(obj, "disabled");
            if (disabledObj is bool && (bool)disabledObj)
                return null;

            double? remPct = null;
            double? rawFrac = GetDouble(obj, "remaining_fraction");
            if (rawFrac.HasValue)
            {
                double f = rawFrac.Value;
                remPct = ClampPct(f <= 1.0 ? f * 100.0 : f);
            }
            if (!remPct.HasValue)
            {
                double? rp = GetDouble(obj, "remaining_percentage");
                if (rp.HasValue) remPct = ClampPct(rp.Value);
            }
            if (!remPct.HasValue)
                return null;

            double? resetsAt = ParseTimestamp(
                GetObj(obj, "reset_time") ?? GetObj(obj, "resets_at"),
                GetObj(obj, "reset_in_seconds"),
                now);

            return new Dictionary<string, object>
            {
                { "bucket_id", bucketId },
                { "remaining_pct", remPct.Value },
                { "used_pct", ClampPct(100.0 - remPct.Value).Value },
                { "remaining_amount", GetObj(obj, "remaining_amount") },
                { "resets_at", resetsAt.HasValue ? (object)resetsAt.Value : null }
            };
        }

        private static void ClassifyAgyBuckets(
            List<Tuple<string, Dictionary<string, object>>> buckets,
            double now,
            out Dictionary<string, object> weekly,
            out Dictionary<string, object> weeklyArgon,
            out Dictionary<string, object> session5h)
        {
            weekly = null;
            weeklyArgon = null;
            session5h = null;
            var weeklyCands = new List<Tuple<int, double, Dictionary<string, object>>>();
            var argonCands = new List<Tuple<int, double, Dictionary<string, object>>>();
            var shortCands = new List<Tuple<int, double, Dictionary<string, object>>>();

            foreach (var item in buckets)
            {
                string low = item.Item1.ToLowerInvariant();
                var b = item.Item2;
                double? resetsAt = GetDouble(b, "resets_at");
                double? horizon = resetsAt.HasValue ? (double?)(resetsAt.Value - now) : null;
                bool isArgon = low.Contains("argon");
                bool is3p = low.StartsWith("3p") || low.Contains("3p-");
                bool isWeekly = low.Contains("week") || low.Contains("7d") || low.Contains("7-day");
                bool isShort = low.Contains("5h") || low.Contains("5-hour") || low.Contains("session") || low.Contains("short") || low.Contains("hourly");
                int prio = is3p ? 2 : (low.Contains("gemini") ? 0 : 1);
                double rem = GetDouble(b, "remaining_pct") ?? 100.0;

                if (isArgon)
                    argonCands.Add(Tuple.Create(prio, rem, b));
                else if (isWeekly)
                    weeklyCands.Add(Tuple.Create(prio, rem, b));
                else if (isShort)
                    shortCands.Add(Tuple.Create(prio, rem, b));
                else if (horizon.HasValue && horizon.Value > 86400.0)
                    weeklyCands.Add(Tuple.Create(prio + 3, rem, b));
                else
                    shortCands.Add(Tuple.Create(prio + 3, rem, b));
            }

            if (weeklyCands.Count > 0)
            {
                weeklyCands.Sort((a, b) => a.Item1 != b.Item1 ? a.Item1.CompareTo(b.Item1) : a.Item2.CompareTo(b.Item2));
                weekly = weeklyCands[0].Item3;
            }
            if (argonCands.Count > 0)
            {
                argonCands.Sort((a, b) => a.Item1 != b.Item1 ? a.Item1.CompareTo(b.Item1) : a.Item2.CompareTo(b.Item2));
                weeklyArgon = argonCands[0].Item3;
            }
            if (shortCands.Count > 0)
            {
                shortCands.Sort((a, b) => a.Item1 != b.Item1 ? a.Item1.CompareTo(b.Item1) : a.Item2.CompareTo(b.Item2));
                session5h = shortCands[0].Item3;
            }
            if (weekly == null && weeklyArgon == null && buckets.Count == 1)
                weekly = buckets[0].Item2;
        }

        private static void UpdateProviderState(
            string statePath,
            string provider,
            Dictionary<string, object> patch,
            JavaScriptSerializer ser)
        {
            string dir = Path.GetDirectoryName(statePath);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);

            bool acquired = false;
            Mutex mutex = null;
            try
            {
                mutex = new Mutex(false, "Local\\AIUsageBar_StateLock");
                try { acquired = mutex.WaitOne(800); }
                catch (AbandonedMutexException) { acquired = true; }

                Dictionary<string, object> state = ReadJsonDict(statePath, ser);
                if (!state.ContainsKey("claude")) state["claude"] = new Dictionary<string, object>();
                if (!state.ContainsKey("antigravity")) state["antigravity"] = new Dictionary<string, object>();
                if (!state.ContainsKey("codex")) state["codex"] = new Dictionary<string, object>();

                var prev = state[provider] as Dictionary<string, object> ?? new Dictionary<string, object>();
                var merged = new Dictionary<string, object>(prev);

                foreach (var kv in patch)
                {
                    if ((kv.Key == "weekly" || kv.Key == "weekly_argon" || kv.Key == "weekly_fable" || kv.Key == "session_5h") && kv.Value is Dictionary<string, object>)
                    {
                        var d = (Dictionary<string, object>)kv.Value;
                        if (GetObj(d, "remaining_pct") == null && prev.ContainsKey(kv.Key))
                            continue;
                        merged[kv.Key] = d;
                    }
                    else if (kv.Value != null)
                    {
                        merged[kv.Key] = kv.Value;
                    }
                }

                state[provider] = merged;
                WriteJsonAtomic(statePath, ser.Serialize(state));
            }
            finally
            {
                if (mutex != null)
                {
                    if (acquired)
                    {
                        try { mutex.ReleaseMutex(); } catch { }
                    }
                    mutex.Dispose();
                }
            }
        }

        private static Dictionary<string, object> ReadJsonDict(string path, JavaScriptSerializer ser)
        {
            if (!File.Exists(path))
                return new Dictionary<string, object>();
            for (int i = 0; i < 5; i++)
            {
                try
                {
                    string txt = File.ReadAllText(path, Encoding.UTF8);
                    if (string.IsNullOrWhiteSpace(txt))
                        return new Dictionary<string, object>();
                    var d = ser.DeserializeObject(txt) as Dictionary<string, object>;
                    return d ?? new Dictionary<string, object>();
                }
                catch
                {
                    Thread.Sleep(20);
                }
            }
            return new Dictionary<string, object>();
        }

        private static void WriteJsonAtomic(string path, string content)
        {
            string dir = Path.GetDirectoryName(path);
            string tmp = Path.Combine(dir, Path.GetFileNameWithoutExtension(path) + "_" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                File.WriteAllText(tmp, content, Utf8NoBom);
                for (int attempt = 0; attempt < 6; attempt++)
                {
                    try
                    {
                        if (File.Exists(path))
                            File.Copy(tmp, path, true);
                        else
                            File.Move(tmp, path);
                        return;
                    }
                    catch (IOException)
                    {
                        if (attempt == 5) throw;
                        Thread.Sleep(25);
                    }
                    catch (UnauthorizedAccessException)
                    {
                        if (attempt == 5) throw;
                        Thread.Sleep(25);
                    }
                }
            }
            finally
            {
                try { if (File.Exists(tmp)) File.Delete(tmp); } catch { }
            }
        }

        private static double NowUnix()
        {
            return (DateTime.UtcNow - UnixEpoch).TotalSeconds;
        }

        private static double? ClampPct(double? val)
        {
            if (!val.HasValue) return null;
            double v = Math.Max(0.0, Math.Min(100.0, val.Value));
            return Math.Round(v, 1);
        }

        private static object GetObj(Dictionary<string, object> d, string key)
        {
            if (d == null) return null;
            object v;
            return d.TryGetValue(key, out v) ? v : null;
        }

        private static Dictionary<string, object> GetDict(Dictionary<string, object> d, string key)
        {
            return GetObj(d, key) as Dictionary<string, object>;
        }

        private static string GetString(Dictionary<string, object> d, string key)
        {
            object v = GetObj(d, key);
            return v == null ? null : v.ToString();
        }

        private static double? GetDouble(Dictionary<string, object> d, string key)
        {
            object v = GetObj(d, key);
            if (v == null) return null;
            try
            {
                if (v is string)
                {
                    double parsed;
                    if (double.TryParse(((string)v).Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out parsed))
                        return parsed;
                    return null;
                }
                return Convert.ToDouble(v, CultureInfo.InvariantCulture);
            }
            catch
            {
                return null;
            }
        }

        private static double? ParseTimestamp(object value, object fallbackInSeconds, double now)
        {
            if (value != null)
            {
                if (value is string)
                {
                    string raw = ((string)value).Trim();
                    if (!string.IsNullOrEmpty(raw))
                    {
                        double num;
                        if (double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out num))
                        {
                            if (num > 1e12) num /= 1000.0;
                            if (num > 0) return num;
                        }
                        DateTimeOffset dto;
                        if (DateTimeOffset.TryParse(
                            raw,
                            CultureInfo.InvariantCulture,
                            DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
                            out dto))
                        {
                            return (dto.UtcDateTime - UnixEpoch).TotalSeconds;
                        }
                    }
                }
                else
                {
                    try
                    {
                        double ts = Convert.ToDouble(value, CultureInfo.InvariantCulture);
                        if (ts > 1e12) ts /= 1000.0;
                        if (ts > 0) return ts;
                    }
                    catch { }
                }
            }

            if (fallbackInSeconds != null)
            {
                try
                {
                    double sec = Convert.ToDouble(fallbackInSeconds, CultureInfo.InvariantCulture);
                    if (sec >= 0) return now + sec;
                }
                catch { }
            }

            return null;
        }

        private static string FormatCountdownCompact(double? resetsAt, double now)
        {
            if (!resetsAt.HasValue) return "";
            long diff = (long)(resetsAt.Value - now);
            if (diff <= 0) return "reset";
            long days = diff / 86400;
            long rem = diff % 86400;
            long hours = rem / 3600;
            long mins = (rem % 3600) / 60;
            if (days > 0) return days + "d " + hours + "h";
            if (hours > 0) return hours + "h " + mins + "m";
            return Math.Max(1, mins) + "m";
        }
    }
}
