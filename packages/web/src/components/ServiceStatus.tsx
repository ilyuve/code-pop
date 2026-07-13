import { useState, useEffect } from 'react';
import { Database, Server, Globe, Wifi, WifiOff, CheckCircle, XCircle, Loader2 } from 'lucide-react';

interface Service {
  name: string;
  icon: React.ReactNode;
  status: 'online' | 'offline' | 'loading';
  url: string;
  lastCheck: Date | null;
}

export const ServiceStatus = () => {
  const [services, setServices] = useState<Service[]>([
    { name: '后端 API', icon: <Server className="w-5 h-5" />, status: 'loading', url: '/health', lastCheck: null },
    { name: '前端', icon: <Globe className="w-5 h-5" />, status: 'online', url: '/', lastCheck: new Date() },
    { name: '数据库', icon: <Database className="w-5 h-5" />, status: 'loading', url: '/api/repos', lastCheck: null },
    { name: 'WebSocket', icon: <Wifi className="w-5 h-5" />, status: 'loading', url: '/ws', lastCheck: null },
  ]);

  const checkService = async (service: Service) => {
    if (service.name === '前端') return;
    
    const startTime = new Date();
    
    try {
      if (service.url === '/ws') {
        const ws = new WebSocket(`ws://${window.location.host}/ws`);
        return new Promise<void>((resolve) => {
          ws.onopen = () => {
            ws.close();
            setServices(prev => prev.map(s => 
              s.name === service.name 
                ? { ...s, status: 'online' as const, lastCheck: new Date() }
                : s
            ));
            resolve();
          };
          ws.onerror = () => {
            setServices(prev => prev.map(s => 
              s.name === service.name 
                ? { ...s, status: 'offline' as const, lastCheck: new Date() }
                : s
            ));
            resolve();
          };
          ws.onclose = () => {
            if (ws.readyState === WebSocket.CLOSED && ws.url) {
              setServices(prev => prev.map(s => 
                s.name === service.name 
                  ? { ...s, status: 'offline' as const, lastCheck: new Date() }
                  : s
              ));
            }
            resolve();
          };
        });
      }
      
      const response = await fetch(service.url, { signal: AbortSignal.timeout(5000) });
      const isOnline = response.ok;
      
      setServices(prev => prev.map(s => 
        s.name === service.name 
          ? { ...s, status: isOnline ? 'online' : 'offline', lastCheck: new Date() }
          : s
      ));
    } catch {
      setServices(prev => prev.map(s => 
        s.name === service.name 
          ? { ...s, status: 'offline', lastCheck: new Date() }
          : s
      ));
    }
  };

  useEffect(() => {
    services.forEach(service => checkService(service));
    
    const interval = setInterval(() => {
      services.forEach(service => checkService(service));
    }, 5000);
    
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status: Service['status']) => {
    switch (status) {
      case 'online': return 'text-green-500';
      case 'offline': return 'text-red-500';
      case 'loading': return 'text-yellow-500';
    }
  };

  const getStatusBg = (status: Service['status']) => {
    switch (status) {
      case 'online': return 'bg-green-50 dark:bg-green-900/20';
      case 'offline': return 'bg-red-50 dark:bg-red-900/20';
      case 'loading': return 'bg-yellow-50 dark:bg-yellow-900/20';
    }
  };

  const getStatusText = (status: Service['status']) => {
    switch (status) {
      case 'online': return '正常';
      case 'offline': return '异常';
      case 'loading': return '检查中';
    }
  };

  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
      <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">服务状态监控</h3>
      <div className="grid grid-cols-2 gap-4">
        {services.map(service => (
          <div 
            key={service.name}
            className={`flex items-center gap-3 p-4 rounded-lg ${getStatusBg(service.status)}`}
          >
            <div className={`${getStatusColor(service.status)}`}>
              {service.status === 'loading' ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : service.status === 'online' ? (
                <CheckCircle className="w-5 h-5" />
              ) : (
                <XCircle className="w-5 h-5" />
              )}
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className={getStatusColor(service.status)}>{service.icon}</span>
                <span className="font-medium text-slate-900 dark:text-white">{service.name}</span>
              </div>
              <div className="text-sm text-slate-500 dark:text-slate-400">
                {getStatusText(service.status)}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
