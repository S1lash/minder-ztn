---
date: '2024-01-04'
source: garmin
user: <owner>
collected_at: '2024-01-04T22:00:00+00:00'
status: ok
metrics_collected:
- sleep
- hrv
- rhr
- stress
- intensity_minutes
- respiration
- steps
metric_failures:
- body_composition: HTTP 500 from upstream
- training_readiness: timeout
- training_status: timeout
metric_failures_count: 3
---

# Garmin daily — 2024-01-04

## Summary
- **Sleep:** slept 7.0h, score 78.
- **Recovery:** HRV overnight 30ms (BALANCED), RHR 53.0.
- **Steps:** 4200.

## Detailed data

### sleep

```yaml
dailySleepDTO:
  sleepTimeSeconds: 25200
  deepSleepSeconds: 5400
  lightSleepSeconds: 14400
  remSleepSeconds: 5040
  awakeSleepSeconds: 360
  sleepScores:
    overall:
      value: 78
```

### hrv

```yaml
hrvSummary:
  lastNightAvg: 30
  status: BALANCED
```

### rhr

```yaml
allMetrics:
  metricsMap:
    WELLNESS_RESTING_HEART_RATE:
    - value: 53.0
      calendarDate: '2024-01-04'
```

### stress

```yaml
avgStressLevel: 33
maxStressLevel: 89
```

### steps

```yaml
totalSteps: 4200
restingHeartRate: 53
```

### intensity_minutes

```yaml
moderateMinutes: 5
vigorousMinutes: 0
```

### respiration

```yaml
avgWakingRespirationValue: 14.5
avgSleepRespirationValue: 15.0
```
