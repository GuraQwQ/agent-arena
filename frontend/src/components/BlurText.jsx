import { useEffect, useState } from "react";

// React Bits 风格的低成本入场文本：只在首次挂载时播放一次。
export function BlurText({ children }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  return <span className={`blur-text ${visible ? "is-visible" : ""}`}>{children}</span>;
}
