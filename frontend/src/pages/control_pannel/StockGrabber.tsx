import React, { useState, useEffect, useRef } from 'react';
import './StockGrabber.css';

interface StockGrabberRequest {
  client_id: string;
  stock_symbol: string;
  order_quantity: number;
  request_per_sec: number;
  broker_no: string;
}

interface StockGrabberResponse {
  status?: string;
  symbol?: string;
  fetch_rate?: number;
  total_fetch_count?: number;
  ltp?: number;
  change_percentage?: number;
  delay?: number;
  rate?: number;
  message?: string;
  error?: string;
  fetchDetails?: {
    fetchRate: number;
    totalFetchCount: number;
    ltp: number;
    script: string;
  };
  twoPercentHigh?: number;
  order_status?: string;
  order_response?: any;
  order_quantity?: number;
  price?: number;
  total_orders?: number;
  details?: any;
}

interface SubmittedInstance {
  session_id: string;
  client_id: string;
  stock_symbol: string;
  order_quantity: number;
  request_per_sec: number;
  broker_no: string;
  status: 'running' | 'stopped';
}

interface StockGrabberProps {
  instanceId: string;
  client_id: string;
  stock_symbol: string;
  onRemove: () => void;
}

const StockGrabber: React.FC<StockGrabberProps> = ({ instanceId, client_id, stock_symbol, onRemove }) => {
  const [formData, setFormData] = useState<StockGrabberRequest>({
    client_id,
    stock_symbol,
    order_quantity: 10,
    request_per_sec: 3.0,
    broker_no: '35',
  });
  const [responses, setResponses] = useState<StockGrabberResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [submittedInstances, setSubmittedInstances] = useState<SubmittedInstance[]>([]);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  const startStockGrabber = async () => {
    if (!formData.client_id || !formData.stock_symbol || !formData.broker_no) {
      setError('Please fill in all required fields');
      return;
    }
    setError(null);
    setIsRunning(true);

    try {
      const res = await fetch('http://localhost:8000/stock_grabber/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!res.ok) {
        throw new Error(`HTTP error: ${res.status}`);
      }

      const data = await res.json();
      setSessionId(data.session_id);

      setSubmittedInstances((prev) => [
        ...prev,
        {
          session_id: data.session_id,
          client_id: formData.client_id,
          stock_symbol: formData.stock_symbol,
          order_quantity: formData.order_quantity,
          request_per_sec: formData.request_per_sec,
          broker_no: formData.broker_no,
          status: 'running',
        },
      ]);

      pollingRef.current = setInterval(async () => {
        try {
          const res = await fetch(`http://localhost:8000/get_stock_grabber_updates/${data.session_id}`);
          if (!res.ok) {
            throw new Error(`HTTP error: ${res.status}`);
          }
          const updateData = await res.json();
          const newUpdates: StockGrabberResponse[] = updateData.updates;
          if (newUpdates.length > 0) {
            setResponses((prev) => [...prev, ...newUpdates].slice(-100));
            const latestUpdate = newUpdates[newUpdates.length - 1];
            if (
              latestUpdate.status === 'stopped' ||
              latestUpdate.status === 'completed' ||
              latestUpdate.status === 'exit' ||
              latestUpdate.status === 'success' ||
              latestUpdate.status === 'failed'
            ) {
              setIsRunning(false);
              setError(latestUpdate.error || latestUpdate.message || 'Stock grabber stopped');
              setSubmittedInstances((prev) =>
                prev.map((instance: SubmittedInstance) =>
                  instance.session_id === data.session_id ? { ...instance, status: 'stopped' } : instance
                )
              );
              if (pollingRef.current) {
                clearInterval(pollingRef.current);
                pollingRef.current = null;
              }
            }
          }
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Failed to fetch updates');
          setIsRunning(false);
          setSubmittedInstances((prev) =>
            prev.map((instance: SubmittedInstance) =>
              instance.session_id === data.session_id ? { ...instance, status: 'stopped' } : instance
            )
          );
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
        }
      }, 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start stock grabber');
      setIsRunning(false);
    }
  };

  const stopStockGrabber = async (targetSessionId: string) => {
    if (targetSessionId) {
      try {
        const res = await fetch(`http://localhost:8000/stop_stock_grabber/${targetSessionId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });

        if (!res.ok) {
          throw new Error(`HTTP error: ${res.status}`);
        }

        if (targetSessionId === sessionId) {
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
          setIsRunning(false);
          setSessionId(null);
        }

        setSubmittedInstances((prev) =>
          prev.map((instance) =>
            instance.session_id === targetSessionId ? { ...instance, status: 'stopped' } : instance
          )
        );
        setResponses((prev) => [
          ...prev,
          { status: 'stopped', message: `Stock grabber ${targetSessionId} stopped` },
        ].slice(-100));
      } catch (err) {
        setError(err instanceof Error ? err.message : `Failed to stop stock grabber ${targetSessionId}`);
      }
    }
  };

  const deleteResponse = (index: number) => {
    setResponses((prev) => prev.filter((_, i) => i !== index));
  };

  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: name === 'order_quantity' || name === 'request_per_sec' ? parseFloat(value) : value,
    }));
  };

  return (
    <div className="container mx-auto p-6 bg-white rounded-lg shadow-lg">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-800">
          Stock Grabber: {formData.client_id} - {formData.stock_symbol}
        </h2>
        <button
          onClick={onRemove}
          className="bg-red-600 text-white py-2 px-4 rounded-md hover:bg-red-700 transition-colors"
        >
          Remove Instance
        </button>
      </div>

      <div className="space-y-6">
        {/* Form Section */}
        <div className="bg-gray-50 p-6 rounded-md shadow-sm">
          <h3 className="text-lg font-semibold mb-4 text-gray-700">Configure Stock Grabber</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Client ID</label>
              <input
                type="text"
                name="client_id"
                value={formData.client_id}
                onChange={handleInputChange}
                disabled={isRunning}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-3 focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                placeholder="Enter Client ID"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Stock Symbol</label>
              <input
                type="text"
                name="stock_symbol"
                value={formData.stock_symbol}
                onChange={handleInputChange}
                disabled={isRunning}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-3 focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                placeholder="Enter Stock Symbol"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Order Quantity</label>
              <input
                type="number"
                name="order_quantity"
                value={formData.order_quantity}
                onChange={handleInputChange}
                disabled={isRunning}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-3 focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                placeholder="Enter Order Quantity"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Request Per Second</label>
              <input
                type="number"
                name="request_per_sec"
                value={formData.request_per_sec}
                onChange={handleInputChange}
                step="0.1"
                disabled={isRunning}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-3 focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                placeholder="Enter Request Per Second"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Broker Number</label>
              <input
                type="text"
                name="broker_no"
                value={formData.broker_no}
                onChange={handleInputChange}
                disabled={isRunning}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-3 focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                placeholder="Enter Broker Number"
              />
            </div>
          </div>
          <div className="flex space-x-4 mt-6">
            <button
              onClick={startStockGrabber}
              disabled={isRunning}
              className={`flex-1 bg-blue-600 text-white py-3 px-4 rounded-md hover:bg-blue-700 transition-colors ${
                isRunning ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            >
              {isRunning ? 'Running...' : 'Start'}
            </button>
            <button
              onClick={() => stopStockGrabber(sessionId || '')}
              disabled={!isRunning}
              className={`flex-1 bg-red-600 text-white py-3 px-4 rounded-md hover:bg-red-700 transition-colors ${
                !isRunning ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            >
              Stop
            </button>
          </div>
        </div>

        {/* Submitted Instances Table */}
        {submittedInstances.length > 0 && (
          <div className="mt-6">
            <h3 className="text-lg font-semibold mb-4 text-gray-700">Submitted Instances</h3>
            <div className="overflow-x-auto">
              <table className="min-w-full bg-white border border-gray-200 rounded-md shadow-sm">
                <thead>
                  <tr className="bg-gray-100">
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Client ID</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Stock Symbol</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Order Quantity</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Request/Sec</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Broker No</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Status</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {submittedInstances.map((instance) => (
                    <tr key={instance.session_id}>
                      <td className="py-3 px-4 border-b text-sm">{instance.client_id}</td>
                      <td className="py-3 px-4 border-b text-sm">{instance.stock_symbol}</td>
                      <td className="py-3 px-4 border-b text-sm">{instance.order_quantity}</td>
                      <td className="py-3 px-4 border-b text-sm">{instance.request_per_sec}</td>
                      <td className="py-3 px-4 border-b text-sm">{instance.broker_no}</td>
                      <td className="py-3 px-4 border-b text-sm">
                        <span
                          className={`${
                            instance.status === 'running' ? 'text-green-600' : 'text-red-600'
                          } font-medium`}
                        >
                          {instance.status.charAt(0).toUpperCase() + instance.status.slice(1)}
                        </span>
                      </td>
                      <td className="py-3 px-4 border-b text-sm">
                        <button
                          onClick={() => stopStockGrabber(instance.session_id)}
                          disabled={instance.status === 'stopped'}
                          className={`py-2 px-4 rounded-md text-white text-sm ${
                            instance.status === 'stopped'
                              ? 'bg-gray-400 cursor-not-allowed'
                              : 'bg-red-600 hover:bg-red-700'
                          }`}
                        >
                          Stop
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Updates Table */}
        {responses.length > 0 && (
          <div className="mt-6">
            <h3 className="text-lg font-semibold mb-4 text-gray-700">Stock Grabber Updates</h3>
            <div className="overflow-x-auto">
              <table className="min-w-full bg-white border border-gray-200 rounded-md shadow-sm">
                <thead>
                  <tr className="bg-gray-100">
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Status</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Symbol</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">LTP</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Fetch Rate</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Order Details</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Message</th>
                    <th className="py-3 px-4 border-b text-left text-sm font-medium text-gray-700">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {responses.map((res, index) => (
                    <tr key={index}>
                      <td className="py-3 px-4 border-b text-sm">
                        <span
                          className={`${
                            res.status === 'success' || res.status === 'stable'
                              ? 'text-green-600'
                              : res.status === 'failed' || res.status === 'stopped' || res.status === 'exit'
                              ? 'text-red-600'
                              : res.status === 'backoff'
                              ? 'text-yellow-600'
                              : 'text-blue-600'
                          } font-medium`}
                        >
                          {(res.status || 'unknown').charAt(0).toUpperCase() + (res.status || 'unknown').slice(1)}
                        </span>
                      </td>
                      <td className="py-3 px-4 border-b text-sm">{res.symbol || res.fetchDetails?.script || '-'}</td>
                      <td className="py-3 px-4 border-b text-sm">
                        {res.ltp ?? res.details?.ltp ?? res.fetchDetails?.ltp ?? '-'}
                      </td>
                      <td className="py-3 px-4 border-b text-sm">
                        {res.fetch_rate ?? res.fetchDetails?.fetchRate ?? res.rate ?? '-'}
                      </td>
                      <td className="py-3 px-4 border-b text-sm">
                        {res.order_status ? (
                          <>
                            <p>
                              <strong>Status:</strong>{' '}
                              <span
                                className={`${
                                  res.order_status === 'success' ? 'text-green-600' : 'text-red-600'
                                }`}
                              >
                                {res.order_status}
                              </span>
                            </p>
                            {res.order_quantity && <p><strong>Qty:</strong> {res.order_quantity}</p>}
                            {res.price && <p><strong>Price:</strong> {res.price}</p>}
                            {res.order_response?.order_id && (
                              <p><strong>Order ID:</strong> {res.order_response.order_id}</p>
                            )}
                          </>
                        ) : res.twoPercentHigh ? (
                          <p><strong>2% High:</strong> {res.twoPercentHigh}</p>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="py-3 px-4 border-b text-sm">
                        {res.message || res.error || (res.delay ? `Delay: ${res.delay}s` : '-')}
                      </td>
                      <td className="py-3 px-4 border-b text-sm">
                        <button
                          onClick={() => deleteResponse(index)}
                          className="py-2 px-4 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="mt-6 p-4 bg-red-100 text-red-700 rounded-md shadow-sm">
            <h3 className="font-semibold text-lg">Error</h3>
            <p>{error}</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default StockGrabber;