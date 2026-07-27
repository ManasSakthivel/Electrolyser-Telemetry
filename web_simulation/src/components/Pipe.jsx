import React from 'react';
import { motion } from 'framer-motion';

const Pipe = ({ path, flowRate = 0, type = 'water', width = 4, opacity = 1 }) => {
    // Flow speed: lower duration = faster
    const duration = flowRate > 0.1 ? 1 / flowRate : 0;

    const color = type === 'h2' ? '#a855f7' : type === 'o2' ? '#06b6d4' : '#3b82f6';

    return (
        <g style={{ opacity }}>
            {/* Background Pipe (Darker, thicker) */}
            <path
                d={path}
                stroke="#1e293b"
                strokeWidth={width + 2}
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
            />

            {/* Inner Pipe (Color tint) */}
            <path
                d={path}
                stroke={color}
                strokeWidth={width}
                strokeOpacity={0.2}
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
            />

            {/* Flow Animation */}
            {duration > 0 && (
                <motion.path
                    d={path}
                    stroke={color}
                    strokeWidth={width}
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeDasharray="10 10"
                    initial={{ strokeDashoffset: 20 }}
                    animate={{ strokeDashoffset: 0 }}
                    transition={{
                        repeat: Infinity,
                        duration: Math.max(0.2, 1 / flowRate), // Cap speed
                        ease: "linear"
                    }}
                />
            )}
        </g>
    );
};

export default Pipe;
