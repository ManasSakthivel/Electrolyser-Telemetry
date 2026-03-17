import React from 'react';
import clsx from 'clsx';

const Stack = ({ current = 0, voltage = 0, temp = 0, cells = {} }) => {
    return (
        <div className="bg-slate-800 border border-slate-600 rounded-xl p-4 w-48">
            <div className="text-center mb-3">
                <div className="text-2xl font-bold text-white">{current.toFixed(1)} A</div>
                <div className="flex justify-center gap-3 text-xs text-slate-400">
                    <span>{voltage.toFixed(1)} V</span>
                    <span>{temp.toFixed(1)} °C</span>
                </div>
            </div>

            {/* Cells Grid */}
            <div className="grid grid-cols-5 gap-1">
                {[1, 2, 3, 4, 5].map(i => {
                    const v = cells[i] || 0;
                    const isWarn = v > 2.2 || v < 1.4;
                    const isErr = v > 2.4 || v < 1.0;

                    return (
                        <div
                            key={i}
                            className={clsx(
                                "h-8 rounded flex items-center justify-center text-[10px] font-mono transition-colors",
                                isErr ? "bg-red-500/20 text-red-400 border border-red-500/50" :
                                    isWarn ? "bg-amber-500/20 text-amber-400 border border-amber-500/50" :
                                        "bg-slate-700 text-slate-300"
                            )}
                            title={`Cell ${i}: ${v.toFixed(3)} V`}
                        >
                            {v.toFixed(2)}
                        </div>
                    );
                })}
            </div>
            <div className="text-center text-[10px] text-slate-500 mt-1">Cell Voltages</div>
        </div>
    );
};

export default Stack;
