import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import prisma from "../config/prisma.js";

const generateAccessToken = (user) => {
    return jwt.sign(
        {
            id: user.id,
            email: user.email,
            role: user.role,
        },
        process.env.JWT_ACCESS_SECRET,
        { expiresIn: "15m" }
    );
};

const generateRefreshToken = (user) => {
    return jwt.sign(
        {
            id: user.id,
        },
        process.env.JWT_REFRESH_SECRET,
        { expiresIn: "7d" }
    );
};

const cookieOptions = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
};

const setAuthCookies = (res, accessToken, refreshToken) => {
    res.cookie("accessToken", accessToken, {
        ...cookieOptions,
        maxAge: 15 * 60 * 1000,
    });

    res.cookie("refreshToken", refreshToken, {
        ...cookieOptions,
        maxAge: 7 * 24 * 60 * 60 * 1000,
    });
};

const clearAuthCookies = (res) => {
    res.clearCookie("accessToken", cookieOptions);
    res.clearCookie("refreshToken", cookieOptions);
};

const safeUserSelect = {
    id: true,
    email: true,
    firstName: true,
    lastName: true,
    role: true,
    specialty: true,
    assignedDoctorId: true,
    isActive: true,
    createdAt: true,
};

const register = async (req, res) => {
    try {
        const {
            email,
            password,
            firstName,
            lastName,
            role,
            specialty,
            assignedDoctorId,
        } = req.body;

        const existingUser = await prisma.user.findUnique({
            where: { email },
        });

        if (existingUser) {
            return res.status(409).json({
                success: false,
                message: "User already exists with this email",
            });
        }

        const passwordHash = await bcrypt.hash(password, 12);

        const user = await prisma.user.create({
            data: {
                email,
                passwordHash,
                firstName,
                lastName,
                role,
                specialty: role === "DOCTOR" ? specialty : null,
                assignedDoctorId: role === "NURSE" ? assignedDoctorId : null,
            },
            select: safeUserSelect,
        });

        return res.status(201).json({
            success: true,
            message: "User registered successfully",
            user,
        });
    }
    catch (error) {
        console.error("Register Error:", error);

        return res.status(500).json({
            success: false,
            message: "Internal server error",
        });
    }
};

const login = async (req, res) => {
    try {
        const { email, password } = req.body;

        const user = await prisma.user.findUnique({
            where: { email },
        });

        if (!user) {
            return res.status(401).json({
                success: false,
                message: "Invalid email or password",
            });
        }

        if (!user.isActive) {
            return res.status(403).json({
                success: false,
                message: "Account is inactive",
            });
        }

        const isPasswordMatched = await bcrypt.compare(password, user.passwordHash);

        if (!isPasswordMatched) {
            return res.status(401).json({
                success: false,
                message: "Invalid email or password",
            });
        }

        const accessToken = generateAccessToken(user);
        const refreshToken = generateRefreshToken(user);

        setAuthCookies(res, accessToken, refreshToken);

        return res.status(200).json({
            success: true,
            message: "Login successful",
            user: {
                id: user.id,
                email: user.email,
                firstName: user.firstName,
                lastName: user.lastName,
                role: user.role,
                specialty: user.specialty,
                assignedDoctorId: user.assignedDoctorId,
                isActive: user.isActive,
            },
        });
    }
    catch (error) {
        console.error("Login Error:", error);

        return res.status(500).json({
            success: false,
            message: "Internal server error",
        });
    }
};

const logout = async (req, res) => {
    try {
        clearAuthCookies(res);

        return res.status(200).json({
            success: true,
            message: "Logout successful",
        });
    }
    catch (error) {
        console.error("Logout Error:", error);

        return res.status(500).json({
            success: false,
            message: "Internal server error",
        });
    }
};

const changePassword = async (req, res) => {
    try {
        const { currentPassword, newPassword } = req.body;
        const userId = req.user.id;

        const user = await prisma.user.findUnique({
            where: { id: userId },
        });

        if (!user) {
            clearAuthCookies(res);

            return res.status(404).json({
                success: false,
                message: "User not found",
            });
        }

        const isPasswordMatched = await bcrypt.compare(
            currentPassword,
            user.passwordHash
        );

        if (!isPasswordMatched) {
            return res.status(400).json({
                success: false,
                message: "Current password is incorrect",
            });
        }

        const newPasswordHash = await bcrypt.hash(newPassword, 12);

        await prisma.user.update({
            where: { id: userId },
            data: {
                passwordHash: newPasswordHash,
            },
        });

        clearAuthCookies(res);

        return res.status(200).json({
            success: true,
            message: "Password changed successfully. Please login again.",
        });
    }
    catch (error) {
        console.error("Change Password Error:", error);

        return res.status(500).json({
            success: false,
            message: "Internal server error",
        });
    }
};

const me = async (req, res) => {
    try {
        return res.status(200).json({
            success: true,
            user: req.user,
        });
    }
    catch (error) {
        console.error("Me Error:", error);

        return res.status(500).json({
            success: false,
            message: "Internal server error",
        });
    }
};

export { register, login, logout, changePassword, me };