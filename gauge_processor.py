import cv2
import numpy as np
import math


class GaugeOCR:
    def __init__(self):
        self.center = None
        self.radius = None
        self.pointer_angle = None
        self.score = None

    def detect_circle(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        if len(contours) < 2:
            self.center = (img.shape[1] // 2, img.shape[0] // 2)
            self.radius = min(img.shape[1], img.shape[0]) // 4
            return True
        
        gauge_contour = contours[0]
        ellipse = cv2.fitEllipse(gauge_contour)
        (cx, cy), (major_axis, minor_axis), angle = ellipse
        
        self.center = (int(cx), int(cy))
        self.radius = int(max(major_axis, minor_axis) / 2 * 0.85)
        
        print(f'  [调试] 检测到的仪表盘圆心: ({cx:.1f}, {cy:.1f}), 半径: {self.radius}')
        
        return True

    def extract_pointer(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        pointer_contour = None
        min_area = self.radius * self.radius * 0.005
        max_area = self.radius * self.radius * 0.05
        
        for cnt in contours[1:]:
            area = cv2.contourArea(cnt)
            if min_area < area < max_area:
                pointer_contour = cnt
                break
        
        if pointer_contour is None:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            lower_blue = np.array([100, 50, 50])
            upper_blue = np.array([130, 255, 255])
            mask_blue = cv2.inRange(hsv, lower_blue, upper_blue)
            
            lower_cyan = np.array([80, 50, 50])
            upper_cyan = np.array([100, 255, 255])
            mask_cyan = cv2.inRange(hsv, lower_cyan, upper_cyan)
            
            mask_pointer = cv2.bitwise_or(mask_blue, mask_cyan)
            
            kernel = np.ones((3, 3), np.uint8)
            mask_pointer = cv2.morphologyEx(mask_pointer, cv2.MORPH_OPEN, kernel)
            
            contours_p, _ = cv2.findContours(mask_pointer, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours_p:
                pointer_contour = max(contours_p, key=cv2.contourArea)
        
        if pointer_contour is None:
            raise ValueError("无法检测到指针")
        
        M = cv2.moments(pointer_contour)
        if M["m00"] != 0:
            px = int(M["m10"] / M["m00"])
            py = int(M["m01"] / M["m00"])
        else:
            rect = cv2.boundingRect(pointer_contour)
            px = rect[0] + rect[2] // 2
            py = rect[1] + rect[3] // 2
        
        return (px, py)

    def calculate_angle(self, pointer_pos):
        if self.center is None or pointer_pos is None:
            return None
        
        dx = pointer_pos[0] - self.center[0]
        dy = pointer_pos[1] - self.center[1]
        
        raw_angle = math.degrees(math.atan2(-dy, dx))
        
        if raw_angle < 0:
            raw_angle += 360
        
        self.pointer_angle = raw_angle
        print(f'  [调试] 检测到的原始角度: {raw_angle:.2f}°, 端点: {pointer_pos}')
        return raw_angle

    def map_angle_to_score(self):
        if self.pointer_angle is None:
            return None
        
        angle = self.pointer_angle
        
        # 仪表盘是半圆形，0分在左边(180度)，50分在正上方(90度)，100分在右边(0度/360度)
        # atan2返回的角度：0度在右边，90度在上方，180度在左边，270度在下方
        # 但由于我们用了 -dy，所以角度是倒置的
        
        # 计算分数：从左边(180度)顺时针到右边(0度/360度)
        # 0分对应180度，100分对应0度/360度
        
        if 90 <= angle <= 180:
            # 从正上方(90度)到左边(180度)：0-50分
            score = 50 * (180 - angle) / 90
        elif 0 <= angle < 90:
            # 从正上方(90度)到右边(0度)：50-100分
            score = 50 + 50 * (90 - angle) / 90
        elif 270 <= angle <= 360:
            # 从右边(360度=0度)到... (处理边界)
            score = 50 + 50 * (90 - angle + 360) / 90
        else:
            score = 50
        
        score = max(0, min(100, score))
        self.score = round(score, 2)
        return self.score

    def process(self, image_path):
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"无法读取图片: {image_path}")
        
        success = self.detect_circle(img)
        if not success:
            raise ValueError("无法检测到仪表盘圆心")
        
        pointer_pos = self.extract_pointer(img)
        if pointer_pos is None:
            raise ValueError("无法提取指针位置")
        
        self.calculate_angle(pointer_pos)
        self.map_angle_to_score()
        
        return {
            'center': self.center,
            'radius': self.radius,
            'pointer_angle': self.pointer_angle,
            'score': self.score
        }


def extract_mindset_gauge(image_path):
    ocr = GaugeOCR()
    try:
        result = ocr.process(image_path)
        angle = result['pointer_angle']
        score = result['score']
        
        print(f"  [仪表盘识别] 角度: {angle:.2f}°, 分数: {score:.2f}")
        
        return result['score']
    except Exception as e:
        print(f"[仪表盘识别] 失败: {e}")
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result = extract_mindset_gauge(sys.argv[1])
        print(f"最终分数: {result}")
