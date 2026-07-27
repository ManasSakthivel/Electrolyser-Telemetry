import React from 'react';
import { motion } from 'framer-motion';

const Tank = ({ level = 0, capacity = 40, label = "Tank", value = 0, unit = "bar" }) => {
    // Level is pressure in this context, max 40 bar
    const pct = Math.min(100, Math.max(0, (level / capacity) * 100));

    return (
        <div className="relative w-24 h-32 bg-slate-800 border-2 border-slate-600 rounded-lg overflow-hidden flex flex-col items-center justify-center">
            {/* Liquid Level */}
            <motion.div
                className="absolute bottom-0 left-0 right-0 bg-h2-color/30 border-t border-h2-color"
                initial={{ height: 0 }}
                animate={{ height: `${pct}%` }}
                transition={{ type: "spring", stiffness: 50 }}
            />

            {/* Content */}
            <div className="z-10 text-center">
                <div className="text-xs text-slate-400 uppercase tracking-wider mb-1">{label}</div>
                <div className="text-lg font-bold text-white">
                    {value.toFixed(1)} <span className="text-xs font-normal text-slate-400">{unit}</span>
                </div>
            </div>
        </div>
    );
};

export default Tank;
