---
date: '2024-01-03'
source: garmin
user: <owner>
collected_at: '2024-01-03T22:00:00+00:00'
status: ok
metrics_collected:
- sleep
- hrv
- rhr
- stress
- training_readiness
- training_status
- intensity_minutes
- respiration
- body_battery
- steps
metric_failures: []
---

# Garmin daily — 2024-01-03

## Summary
- **Sleep:** slept 4.5h, score 55, stages — deep 1.0h, REM 0.5h, light 2.5h, awake 0.5h.
- **Recovery:** HRV overnight 22ms (UNBALANCED), RHR 60.0, Body Battery 35→25.
- **Stress:** avg 50, max 95.
- **Training:** DETRAINING (acute 0, chronic 100, ACWR LOW).
- **Training readiness:** 50 (LOW).
- **Steps:** 1500.

## Detailed data

### sleep

```yaml
dailySleepDTO:
  sleepTimeSeconds: 16200
  deepSleepSeconds: 3600
  lightSleepSeconds: 9000
  remSleepSeconds: 1800
  awakeSleepSeconds: 1800
  sleepScores:
    overall:
      value: 55
```

### hrv

```yaml
hrvSummary:
  lastNightAvg: 22
  status: UNBALANCED
```

### rhr

```yaml
allMetrics:
  metricsMap:
    WELLNESS_RESTING_HEART_RATE:
    - value: 60.0
      calendarDate: '2024-01-03'
```

### stress

```yaml
avgStressLevel: 50
maxStressLevel: 95
```

### body_battery

```yaml
- date: '2024-01-03'
  charged: 25
  drained: 35
```

### steps

```yaml
totalSteps: 1500
bodyBatteryHighestValue: 35
bodyBatteryAtWakeTime: 30
bodyBatteryMostRecentValue: 20
restingHeartRate: 60
```

### training_readiness

```yaml
- score: 50
  level: LOW
  acuteLoad: 0
```

### training_status

```yaml
mostRecentTrainingStatus:
  latestTrainingStatusData:
    'device-1':
      trainingStatusFeedbackPhrase: DETRAINING
      acuteTrainingLoadDTO:
        dailyTrainingLoadAcute: 0
        dailyTrainingLoadChronic: 100
        dailyAcuteChronicWorkloadRatio: 0.0
        acwrStatus: LOW
```

### intensity_minutes

```yaml
moderateMinutes: 0
vigorousMinutes: 0
```

### respiration

```yaml
avgWakingRespirationValue: 16.0
avgSleepRespirationValue: 17.0
```
