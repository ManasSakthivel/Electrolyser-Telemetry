import React from 'react';
import { motion } from 'framer-motion';
import { Fan, Disc } from 'lucide-react';
import clsx from 'clsx';

const Pump = ({ active = false, fault = false, label = "Pump" }) => {
    return (
        <div className="flex flex-col items-center gap-2">
            <div className={clsx(
                "w-12 h-12 rounded-full border-2 flex items-center justify-center bg-slate-800",
                fault ? "border-red-500 text-red-500" : active ? "border-green-500 text-green-500" : "border-slate-600 text-slate-600"
            )}>
                <motion.div
                    animate={active && !fault ? { rotate: 360 } : { rotate: 0 }}
                    transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
                >
                    <Disc size={24} />
                </motion.div>
            </div>
            <span className="text-xs text-slate-400">{label}</span>
        </div>
    );
};

export default Pump;
