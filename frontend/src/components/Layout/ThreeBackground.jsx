import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { useApp } from '../../context/AppContext';

export default function ThreeBackground() {
  const containerRef = useRef(null);
  const { theme } = useApp();

  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    
    const scene = new THREE.Scene();
    const w = container.clientWidth || window.innerWidth;
    const h = container.clientHeight || window.innerHeight;
    
    const camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });

    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Subtle ambient lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    // Theme parameter configurations
    const isLight = theme === 'light';
    const cyanColor = isLight ? 0x008ba3 : 0x4FE3FF;
    const violetColor = isLight ? 0x5c4eb5 : 0x8B7CFF;
    const envelopeOpacity = isLight ? 0.35 : 0.12;
    const pathOpacity = isLight ? 0.15 : 0.04;
    const packetOpacity = isLight ? 0.50 : 0.25;
    const blendMode = isLight ? THREE.NormalBlending : THREE.AdditiveBlending;

    // Dual point lights configured for the current theme
    const cyanLight = new THREE.PointLight(cyanColor, isLight ? 1.5 : 2, 80);
    cyanLight.position.set(-15, 10, 5);
    scene.add(cyanLight);

    const violetLight = new THREE.PointLight(violetColor, isLight ? 2 : 2.5, 80);
    violetLight.position.set(15, -10, 5);
    scene.add(violetLight);

    // Custom 3D Wireframe Envelope Geometry
    const createEnvelopeGeometry = () => {
      const width = 1.0;
      const height = 0.6;
      const geometry = new THREE.BufferGeometry();
      const vertices = new Float32Array([
        // Box outline
        -width/2, -height/2, 0,
         width/2, -height/2, 0,
         width/2,  height/2, 0,
        -width/2,  height/2, 0,
        -width/2, -height/2, 0,
        // Triangular flap lines
        -width/2,  height/2, 0,
         0,        0.05,      0.15,
         width/2,  height/2, 0,
        // Bottom folds
        -width/2, -height/2, 0,
         0,       -0.08,      0.08,
         width/2, -height/2, 0
      ]);
      geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
      return geometry;
    };

    const envelopeGeom = createEnvelopeGeometry();
    const envelopesCount = 14;
    const envelopes = [];

    // Create floating envelopes using theme colors and weights
    for (let i = 0; i < envelopesCount; i++) {
      const color = i % 2 === 0 ? cyanColor : violetColor;
      const mat = new THREE.LineBasicMaterial({
        color: color,
        transparent: true,
        opacity: envelopeOpacity,
        linewidth: isLight ? 1.5 : 1
      });

      const lineMesh = new THREE.Line(envelopeGeom, mat);
      
      lineMesh.position.set(
        (Math.random() - 0.5) * 40,
        (Math.random() - 0.5) * 30,
        (Math.random() - 0.5) * 12
      );
      
      const scale = 0.5 + Math.random() * 0.5;
      lineMesh.scale.set(scale, scale, scale);

      envelopes.push({
        mesh: lineMesh,
        speedY: 0.005 + Math.random() * 0.012,
        rotX: (Math.random() - 0.5) * 0.004,
        rotY: (Math.random() - 0.5) * 0.005,
        rotZ: (Math.random() - 0.5) * 0.003
      });

      scene.add(lineMesh);
    }

    // Curved flight paths crossing background
    const curvePointsList = [
      [new THREE.Vector3(-25, 12, -5), new THREE.Vector3(-8, 5, 2), new THREE.Vector3(8, -8, -2), new THREE.Vector3(25, -12, -5)],
      [new THREE.Vector3(-25, -8, -3), new THREE.Vector3(-10, -12, 0), new THREE.Vector3(10, 8, 3), new THREE.Vector3(25, 6, -3)],
      [new THREE.Vector3(-20, 15, -8), new THREE.Vector3(-2, 0, 1), new THREE.Vector3(22, -15, -8)],
      [new THREE.Vector3(-25, 0, -4), new THREE.Vector3(-12, 8, 0), new THREE.Vector3(12, -8, 0), new THREE.Vector3(25, 0, -4)],
    ];

    const flightPaths = [];
    const packetParticles = [];

    curvePointsList.forEach((pts, index) => {
      const curve = new THREE.CatmullRomCurve3(pts);
      const points = curve.getPoints(50);
      const curveGeom = new THREE.BufferGeometry().setFromPoints(points);
      
      const curveMat = new THREE.LineBasicMaterial({
        color: index % 2 === 0 ? cyanColor : violetColor,
        transparent: true,
        opacity: pathOpacity
      });

      const pathLine = new THREE.Line(curveGeom, curveMat);
      scene.add(pathLine);

      flightPaths.push({ curve });

      // Create a moving data packet along this curve
      const packetGeom = new THREE.BufferGeometry();
      packetGeom.setAttribute('position', new THREE.BufferAttribute(new Float32Array([0, 0, 0]), 3));
      
      const packetMat = new THREE.PointsMaterial({
        color: index % 2 === 0 ? cyanColor : violetColor,
        size: isLight ? 0.35 : 0.28,
        transparent: true,
        opacity: packetOpacity,
        blending: blendMode
      });

      const packet = new THREE.Points(packetGeom, packetMat);
      scene.add(packet);

      packetParticles.push({
        mesh: packet,
        curve: curve,
        progress: Math.random(),
        speed: 0.0008 + Math.random() * 0.0012
      });
    });

    camera.position.z = 18;

    let animationId;

    const animate = () => {
      animationId = requestAnimationFrame(animate);

      // Animate floating envelopes
      envelopes.forEach((env) => {
        env.mesh.position.y += env.speedY;
        env.mesh.rotation.x += env.rotX;
        env.mesh.rotation.y += env.rotY;
        env.mesh.rotation.z += env.rotZ;

        // Wrap around Y
        if (env.mesh.position.y > 16) {
          env.mesh.position.y = -16;
          env.mesh.position.x = (Math.random() - 0.5) * 40;
        }
      });

      // Animate flight packets along curves
      packetParticles.forEach((packet) => {
        packet.progress += packet.speed;
        if (packet.progress > 1) {
          packet.progress = 0;
        }

        const point = packet.curve.getPointAt(packet.progress);
        packet.mesh.position.copy(point);
      });

      renderer.render(scene, camera);
    };

    animate();

    const handleResize = () => {
      const width = container.clientWidth || window.innerWidth;
      const height = container.clientHeight || window.innerHeight;
      
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
  }, [theme]);

  return (
    <div
      ref={containerRef}
      className="three-background-canvas"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        zIndex: 0,
        pointerEvents: 'none',
        opacity: theme === 'light' ? 0.35 : 0.35, // Set identical opacities for clean visibility
        mixBlendMode: theme === 'light' ? 'normal' : 'screen'
      }}
    />
  );
}
