import service from './index'

export const getSystemStatus = () => {
  return service.get('/api/system/status')
}

export const getSimulationMetrics = (simulationId) => {
  return service.get(`/api/system/simulations/${simulationId}/metrics`)
}
