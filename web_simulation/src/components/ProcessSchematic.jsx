import React from 'react';
import { Zap, Activity, Droplets, Wind, Gauge } from 'lucide-react';
import Pipe from './Pipe';
import Tank from './Tank';
import Pump from './Pump';
import Stack from './Stack';

const ProcessSchematic = ({ id, data }) => {
    const { current, voltage, temp, h2, o2, water, tank, cells } = data;

    const isRunning = current > 0.1;
    const isFault = temp > 80 || tank > 35 || Object.values(cells).some(v => v > 2.3 || v < 1.3);

    // SVG Coordinate System: 800x400
    // Layout:
    // Water In (50, 300) -> Pump (200, 300) -> Stack (400, 250)
    // Stack (400, 250) -> H2 Out (Top: 600, 150) -> Tank (700, 150)
    // Stack (400, 250) -> O2 Out (Bot: 600, 350) -> Vent (700, 350)

    return (
        <div className="glass-panel rounded-2xl p-1 relative overflow-hidden transition-all duration-300 hover:shadow-2xl hover:border-white/20">
            {/* Title Bar Overlay */}
            <div className="absolute top-4 left-4 z-20 flex items-center gap-3">
                <div className={`p-2 rounded-lg border ${isRunning ? 'bg-green-500/10 border-green-500/50' : 'bg-slate-700/50 border-slate-600'}`}>
                    <h2 className="text-lg font-bold text-white flex items-center gap-2">
                        {id} <span className="text-xs font-normal text-slate-400 opacity-75">UNIT</span>
                    </h2>
                </div>
                {isFault && (
                    <div className="px-3 py-1 rounded bg-red-500/20 border border-red-500 text-red-400 text-xs font-bold animate-pulse">
                        FAULT DETECTED
                    </div>
                )}
            </div>

            {/* Main Schematic SVG */}
            <div className="relative w-full aspect-[2/1] bg-slate-900/40">
                <svg viewBox="0 0 800 400" className="w-full h-full">
                    {/* Grid Lines (Subtle) */}
                    <defs>
                        <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="white" strokeOpacity="0.03" strokeWidth="1" />
                        </pattern>
                    </defs>
                    <rect width="100%" height="100%" fill="url(#grid)" />

                    {/* --- PIPES --- */}

                    {/* Water Line: Start -> Pump -> Stack */}
                    <Pipe path="M 50 300 L 200 300 L 350 300 L 350 280" flowRate={water} type="water" />

                    {/* H2 Line: Stack Top -> Separator */}
                    <Pipe path="M 400 180 L 400 150 L 650 150" flowRate={h2} type="h2" />

                    {/* O2 Line: Stack Side -> Vent */}
                    <Pipe path="M 450 230 L 500 230 L 500 350 L 650 350" flowRate={o2} type="o2" />


                    {/* --- COMPONENT PLACEHOLDERS (Visuals drawn in SVG) --- */}

                    {/* Pump Base */}
                    <circle cx="200" cy="300" r="25" fill="#0f172a" stroke="#334155" strokeWidth="2" />

                    {/* Separator Tank Base */}
                    <rect x="650" y="100" width="60" height="100" rx="4" fill="#0f172a" stroke="#334155" strokeWidth="2" />

                    {/* Vent Base */}
                    <path d="M 650 350 L 710 350 L 720 330 L 640 330 Z" fill="#0f172a" stroke="#334155" strokeWidth="2" opacity="0.5" />

                </svg>

                {/* --- REACT COMPONENT OVERLAYS (Absolute Positioning) --- */}

                {/* Water Input Label */}
                <div className="absolute left-[2%] top-[72%] text-xs text-blue-400 font-mono">
                    H₂O SUPPLY
                    <div className="bg-slate-900/80 px-1 rounded text-white">{water.toFixed(1)} L/m</div>
                </div>

                {/* Pump (Centered at 200, 300) */}
                <div className="absolute left-[25%] top-[75%] -translate-x-1/2 -translate-y-1/2">
                    <Pump active={isRunning} fault={isFault && water < 0.1} label="" />
                    <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 text-[10px] text-slate-500">P-101</div>
                </div>

                {/* Stack (Centered at 400, 230) */}
                <div className="absolute left-[50%] top-[50%] -translate-x-1/2 -translate-y-1/2 z-10">
                    <div className={`transition-all duration-500 ${isRunning ? 'drop-shadow-[0_0_20px_rgba(59,130,246,0.4)]' : ''}`}>
                        <Stack current={current} voltage={voltage} temp={temp} cells={cells} />
                    </div>
                </div>

                {/* Separator Tank (Centered at 680, 150) */}
                <div className="absolute left-[85%] top-[37%] -translate-x-1/2 -translate-y-1/2">
                    <Tank level={tank} value={tank} label="H₂ Sep" unit="bar" />
                </div>

                {/* H2 Output Label */}
                <div className="absolute left-[85%] top-[15%] text-xs text-purple-400 font-mono text-center">
                    H₂ OUT
                    <div className="bg-slate-900/80 px-1 rounded text-white">{h2.toFixed(2)} L/m</div>
                </div>

                {/* O2 Vent Label */}
                <div className="absolute left-[85%] top-[88%] -translate-x-1/2 text-xs text-cyan-400 font-mono text-center">
                    O₂ VENT
                    <div className="bg-slate-900/80 px-1 rounded text-white">{o2.toFixed(2)} L/m</div>
                </div>

            </div>
        </div>
    );
};

export default ProcessSchematic;
