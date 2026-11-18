import { writeFileSync } from 'fs';
import { createCanvas } from 'canvas';

const sizes = [192, 384, 512];

sizes.forEach(size => {
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext('2d');
  
  // Background
  ctx.fillStyle = '#000000';
  ctx.beginPath();
  ctx.roundRect(0, 0, size, size, size * 0.125);
  ctx.fill();
  
  // Main diamond shape
  ctx.fillStyle = '#22c55e';
  ctx.strokeStyle = '#16a34a';
  ctx.lineWidth = size * 0.016;
  ctx.lineJoin = 'round';
  
  ctx.beginPath();
  ctx.moveTo(size * 0.5, size * 0.25);
  ctx.lineTo(size * 0.75, size * 0.4375);
  ctx.lineTo(size * 0.5, size * 0.625);
  ctx.lineTo(size * 0.25, size * 0.4375);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  
  // Inner diamond
  ctx.fillStyle = '#10b981';
  ctx.strokeStyle = '#059669';
  ctx.lineWidth = size * 0.012;
  
  ctx.beginPath();
  ctx.moveTo(size * 0.5, size * 0.375);
  ctx.lineTo(size * 0.65625, size * 0.5);
  ctx.lineTo(size * 0.5, size * 0.625);
  ctx.lineTo(size * 0.34375, size * 0.5);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  
  // Bottom chevron
  ctx.strokeStyle = '#22c55e';
  ctx.lineWidth = size * 0.023;
  ctx.lineCap = 'round';
  
  ctx.beginPath();
  ctx.moveTo(size * 0.390625, size * 0.625);
  ctx.lineTo(size * 0.5, size * 0.703125);
  ctx.lineTo(size * 0.609375, size * 0.625);
  ctx.stroke();
  
  // Left accent
  ctx.lineWidth = size * 0.016;
  ctx.beginPath();
  ctx.moveTo(size * 0.2734375, size * 0.546875);
  ctx.lineTo(size * 0.390625, size * 0.625);
  ctx.lineTo(size * 0.2734375, size * 0.703125);
  ctx.stroke();
  
  // Right accent
  ctx.beginPath();
  ctx.moveTo(size * 0.7265625, size * 0.546875);
  ctx.lineTo(size * 0.609375, size * 0.625);
  ctx.lineTo(size * 0.7265625, size * 0.703125);
  ctx.stroke();
  
  // Center dot
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.arc(size * 0.5, size * 0.5, size * 0.03125, 0, Math.PI * 2);
  ctx.fill();
  
  const buffer = canvas.toBuffer('image/png');
  writeFileSync(`public/icon-${size}x${size}.png`, buffer);
  console.log(`Generated icon-${size}x${size}.png`);
});

console.log('All icons generated successfully!');
