import jwt from "jsonwebtoken";
import prisma from "../config/db.js";
import logger from "../utils/logger.js";
import { visitRoom } from "../services/socketRelay.services";


//Socket Authentication middleware

export const socketAuthMiddleware = (socket,next) => {
    try {
        const cookieHeader = socket.handshake.headers.cookie || ''
        const tokenFromCookie = cookieHeader.split(';').map((c)=>c.trim()).find((c)=>c.startsWith('accessToken='))?.split('=')[1];

        const token = tokenFromCookie || socket.handshake.auth?.token;

        if(!token) {
            return next(new Error('Authentication required'));
        }

        const decoded = jwt.verify(token,process.env.JWT_ACCESS_SECRET);
        socket.userId = decoded.userId;
        socket.userRole = decoded.role;

        next();
    } catch (error) {
        logger.warn(`Socket auth failed: ${error.message}`);
        next(new Error('Invalid or expired token'));
    }
}

export const registerVisitSocketHandlers = (io) => {
    io.use(socketAuthMiddleware);

    io.on('connection',(socket) => {
        logger.info(`User ${socket.userId} (${socket.userRole}) connected: ${socket.id}`);

        socket.on('visit:join',async (visitId,callback) => {
            try {
                const visit = await prisma.visit.findUnique({
                    where: {id: visitId},
                    select: {doctorId: true}
                })

                if(!visit) {
                    return callback?.({success:false,error:'Visit not found'});
                }

                const canAccess = await checkVisitSocketAccess(socket,visit);
                if(!canAccess) {
                    return  callback?.({success: false,error: 'Access denied'})
                }

                const room = visitRoom(visitId);
                socket.join(room);

                logger.info(`Socket ${socket.id} (user ${socket.userId}) joined room ${room}`);
                callback?.({success: true});
            } catch (error) {
                logger.error(`visit:join error: ${error.message}`);
                callback?.({success: false,error:'internal error'});
            }
        });

        socket.on('visit:leave',(visitId) => {
            const room = visitRoom(visitId);
            socket.leave(room);
            logger.debug(`Socket ${socket.id} left room ${room}`);
        });
        socket.on('disconnect',(reason) => {
            logger.info(`Socket disconnected: userId=${socket.userId}, reason=${reason}`);
        })
    })
}

export const checkVisitSocketAccess = async (socket,visit) => {
    if(socket.userRole === 'ADMIN') return true;
    if(socket.userRole === 'DOCTOR') {
        return visit.doctorId === socket.userId;
    }

    if(socket.userRole === 'NURSE') {
        const nurse = await prisma.user.findUnique({
            where: {id: socket.userId},
            select: {assignedDoctorId: true},
        });
        return nurse?.assignedDoctorId === visit.doctorId;
    }

    return false;
}

