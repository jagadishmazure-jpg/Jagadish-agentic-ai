// Azure Monitor alerting for the workload: one action group (optional on-call email), metric alert
// rules on the platform resources and KQL log alert rules on Application Insights.
// Mirrors infra/terraform/modules/alerts. Written and built offline; not deployed.
param location string
param tags object
param resourceToken string
@maxLength(12)
param actionGroupShortName string
@description('Optional on-call address. Empty = alerts still fire in Azure Monitor but notify nobody.')
param alertEmail string = ''
param appInsightsId string
@description('Metric alert rules: { name, scope, namespace, metric, aggregation, operator, threshold, severity, description }')
param metricAlerts array = []
@description('KQL alert rules on Application Insights: { name, query, threshold, severity, description }')
param logAlerts array = []

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-${resourceToken}'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: actionGroupShortName
    enabled: true
    emailReceivers: empty(alertEmail) ? [] : [{ name: 'on-call', emailAddress: alertEmail, useCommonAlertSchema: true }]
  }
}

resource metric 'Microsoft.Insights/metricAlerts@2018-03-01' = [for a in metricAlerts: {
  name: 'ma-${a.name}-${resourceToken}'
  location: 'global'
  tags: tags
  properties: {
    description: a.description
    severity: a.severity
    enabled: true
    scopes: [a.scope]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: a.name
          metricNamespace: a.namespace
          metricName: a.metric
          timeAggregation: a.aggregation
          operator: a.operator
          threshold: a.threshold
        }
      ]
    }
    actions: [{ actionGroupId: actionGroup.id }]
  }
}]

resource log 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for a in logAlerts: {
  name: 'la-${a.name}-${resourceToken}'
  location: location
  tags: tags
  properties: {
    description: a.description
    severity: a.severity
    enabled: true
    scopes: [appInsightsId]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: a.query
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: a.threshold
          failingPeriods: { minFailingPeriodsToAlert: 1, numberOfEvaluationPeriods: 1 }
        }
      ]
    }
    actions: { actionGroups: [actionGroup.id] }
  }
}]

output actionGroupId string = actionGroup.id
output metricAlertNames array = [for (a, i) in metricAlerts: metric[i].name]
output logAlertNames array = [for (a, i) in logAlerts: log[i].name]
