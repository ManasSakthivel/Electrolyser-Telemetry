import React from 'react';
import { Activity } from 'lucide-react';
import ProcessSchematic from './ProcessSchematic';

const DigitalTwin = ({ data }) => {
    const { EL1, EL2, PLANT } = data;

    return (
        <div className="min-h-screen p-4 md:p-8 text-scada-text font-sans relative overflow-hidden">
            {/* Header */}
            <header className="flex flex-col md:flex-row justify-between items-center mb-8 border-b border-white/10 pb-4 relative z-10 gap-4">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-blue-500/20 border border-blue-500/50 shadow-[0_0_15px_rgba(59,130,246,0.5)]">
                        <Activity className="text-blue-400" size={28} />
                    </div>
                    <div>
                        <h1 className="text-2xl font-bold tracking-tight text-white drop-shadow-md leading-none">
                            Electrolyser Plant A
                        </h1>
                        <span className="text-slate-400 font-normal text-sm">Real-time Telemetry & Control</span>
                    </div>
                </div>
                <div className="flex gap-6 bg-slate-900/50 p-3 rounded-xl border border-white/5">
                    <MetricBox label="Irradiance 1" value={PLANT.irr1.toFixed(0)} unit="W/m²" />
                    <div className="w-px bg-white/10"></div>
                    <MetricBox label="Irradiance 2" value={PLANT.irr2.toFixed(0)} unit="W/m²" />
                </div>
            </header>

            {/* Main Grid */}
            <div className="grid grid-cols-1 gap-8 max-w-6xl mx-auto relative z-10">
                {/* EL1 */}
                <ProcessSchematic id="EL1" data={EL1} />
                {/* EL2 */}
                <ProcessSchematic id="EL2" data={EL2} />
            </div>
        </div>
    );
};

const MetricBox = ({ label, value, unit }) => (
    <div className="flex flex-col items-end min-w-[100px]">
        <span className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">{label}</span>
        <span className="text-xl font-bold text-amber-400 drop-shadow-[0_0_5px_rgba(245,158,11,0.5)] font-mono">
            {value} <span className="text-xs text-slate-500 font-sans">{unit}</span>
        </span>
    </div>
);

export default DigitalTwin;
