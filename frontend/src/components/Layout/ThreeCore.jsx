import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { useApp } from '../../context/AppContext';

export default function ThreeCore({ syncing }) {
  const containerRef = useRef(null);
  const { theme } = useApp();

  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const scene = new THREE.Scene();
    const w = container.clientWidth || 300;
    const h = container.clientHeight || 300;

    const camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 100);
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });

    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Ambient lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    // Theme parameter configurations
    const isLight = theme === 'light';
    const coreColor = isLight ? 0x008ba3 : 0x4FE3FF;
    const baseOpacity = isLight ? 0.65 : 0.35;
    const particleOpacity = isLight ? 0.85 : 0.6;
    const blendMode = isLight ? THREE.NormalBlending : THREE.AdditiveBlending;

    // Core point light (Cyan / Teal depending on theme)
    const coreLight = new THREE.PointLight(coreColor, 3.5, 20);
    scene.add(coreLight);

    // AI Core Mesh - TorusKnot wireframe for futuristic quantum structure
    const geometry = new THREE.TorusKnotGeometry(1.6, 0.45, 120, 16);
    const material = new THREE.MeshBasicMaterial({
      color: coreColor,
      wireframe: true,
      transparent: true,
      opacity: baseOpacity,
      blending: blendMode
    });

    const coreMesh = new THREE.Mesh(geometry, material);
    scene.add(coreMesh);

    // Outer quantum shell (orbital particles)
    const particleGeometry = new THREE.BufferGeometry();
    const particleCount = 150;
    const positions = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const r = 2.8 + Math.random() * 0.4; // Orbit radius

      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);
    }

    particleGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    
    const particleMaterial = new THREE.PointsMaterial({
      color: coreColor,
      size: isLight ? 0.09 : 0.08,
      transparent: true,
      opacity: particleOpacity,
      blending: blendMode
    });

    const shell = new THREE.Points(particleGeometry, particleMaterial);
    scene.add(shell);

    camera.position.z = 6;

    let animationId;
    
    const animate = () => {
      animationId = requestAnimationFrame(animate);

      const time = Date.now() * 0.001;
      
      // Speed up spin and pulse if syncing is active!
      const speedMultiplier = syncing ? 4.5 : 1.0;
      
      // Core rotation
      coreMesh.rotation.x += 0.004 * speedMultiplier;
      coreMesh.rotation.y += 0.006 * speedMultiplier;
      
      // Shell rotation (in reverse)
      shell.rotation.y -= 0.002 * speedMultiplier;
      shell.rotation.z += 0.001 * speedMultiplier;

      // Pulsing scale factor based on time
      const pulseSpeed = syncing ? 8.0 : 2.5;
      const pulseDepth = syncing ? 0.12 : 0.06;
      const scale = 1.0 + Math.sin(time * pulseSpeed) * pulseDepth;
      
      coreMesh.scale.set(scale, scale, scale);
      
      // Morph wireframe opacity to pulse visually
      material.opacity = (syncing ? (baseOpacity + 0.2) : baseOpacity) + Math.sin(time * 4.0) * 0.05;

      renderer.render(scene, camera);
    };

    animate();

    const handleResize = () => {
      const width = container.clientWidth || 300;
      const height = container.clientHeight || 300;
      
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      
      renderer.setSize(width, height);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      cancelAnimationFrame(animationId);
      window.removeEventListener('resize', handleResize);
      renderer.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [syncing, theme]);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent'
      }}
    />
  );
}
